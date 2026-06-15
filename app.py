"""
FastAPI приложение: загрузка PDF -> анализ -> предпросмотр/редактирование -> docx.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import time
import traceback
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass

import json

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import analyzer
import application_generator
import doc_generator
from intake_store import IntakeStore
from queue_store import QueueStore
from syslog import log

app = FastAPI(title="Экспертное заключение — генератор")

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

DATA_DIR = Path(__file__).parent / ".data"
STORE = QueueStore(DATA_DIR / "queue.sqlite3")
INTAKE_STORE = IntakeStore(DATA_DIR / "intake.sqlite3")

CONCLUSIONS_DIR = DATA_DIR / "conclusions"
APPLICATIONS_DIR = DATA_DIR / "applications"
CONCLUSIONS_DIR.mkdir(parents=True, exist_ok=True)
APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job store for async PDF analysis
_analyze_jobs: dict[str, dict] = {}

# SSE clients: one asyncio.Queue per connected browser tab
_sse_clients: list[asyncio.Queue] = []


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CertOut(BaseModel):
    page: int
    course_title: str = ""
    provider: str = ""
    hours: str = ""
    grade: str = ""
    date: str = ""
    student_name: str = ""
    certificate_id: str = ""
    verify_url: str = ""


class AnalyzeResponse(BaseModel):
    student_name: str = ""
    group: str = ""
    program_code: str = ""
    course_year: str = ""
    phone: str = ""
    application_date: str = ""
    disciplines: list[str] = Field(default_factory=list)
    certificates: list[CertOut] = Field(default_factory=list)
    mapping: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    plan_data: dict[str, dict] = Field(default_factory=dict)


class CourseIn(BaseModel):
    course_title: str = ""
    provider: str = ""
    hours: str = ""
    grade: str = ""
    date: str = ""


class RowIn(BaseModel):
    discipline: str = ""
    plan_credits: str = ""
    total_hours: str = ""
    grade_points: str = ""
    compliance: str = "полное"
    note: str = ""
    final_grade: str = ""
    courses: list[CourseIn] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    student_name: str = ""
    program_code: str = ""
    course_year: str = ""
    rows: list[RowIn] = Field(default_factory=list)


class QueueEditState(BaseModel):
    student: dict[str, Any] = Field(default_factory=dict)
    disciplines: list[dict[str, Any]] = Field(default_factory=list)
    certificates: list[dict[str, Any]] = Field(default_factory=list)


def drive_file_view_url(drive_file_id: str) -> str:
    fid = (drive_file_id or "").strip()
    if not fid or fid.startswith("intake_") or fid.startswith("upload_"):
        return ""
    return f"https://drive.google.com/file/d/{fid}/view"


def _row_to_sse_dict(r: "RequestRow") -> dict:
    a = r.analyze_json or {}
    return {
        "id": r.id,
        "status": r.status,
        "drive_file_id": r.drive_file_id,
        "filename": r.filename,
        "student_name": a.get("student_name") or "",
        "group": a.get("group") or "",
        "faculty": a.get("faculty") or "",
        "department": a.get("department") or "",
        "created_at": r.created_at,
        "updated_at": r.updated_at,
        "drive_file_url": drive_file_view_url(r.drive_file_id),
        "output_drive_file_id": r.output_drive_file_id or "",
        "error": r.error or "",
    }


def _broadcast_sse(event: dict) -> None:
    dead = []
    for q in _sse_clients:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _sse_clients.remove(q)
        except ValueError:
            pass


class QueueListItem(BaseModel):
    id: int
    drive_file_id: str
    filename: str
    status: str
    student_name: str = ""
    group: str = ""
    faculty: str = ""
    department: str = ""
    created_at: int = 0
    updated_at: int
    drive_file_url: str = ""
    output_drive_file_id: str = ""
    error: str = ""


class QueueListResponse(BaseModel):
    items: list[QueueListItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def _resolve_keys(
    gemini_form: str | None, openrouter_form: str | None
) -> tuple[str | None, str | None]:
    gemini = (gemini_form or "").strip() or os.environ.get("GEMINI_API_KEY") or None
    openrouter = (
        (openrouter_form or "").strip()
        or os.environ.get("OPENROUTER_API_KEY")
        or None
    )
    if not gemini and not openrouter:
        raise HTTPException(
            status_code=400,
            detail=(
                "Не указан ни один API ключ. Введите OpenRouter или Gemini в форме "
                "(или установите в окружении). OpenRouter: https://openrouter.ai/keys, "
                "Gemini: https://aistudio.google.com/apikey"
            ),
        )
    return gemini, openrouter


def _env_llm_keys() -> tuple[str | None, str | None]:
    return (
        os.environ.get("GEMINI_API_KEY") or None,
        os.environ.get("OPENROUTER_API_KEY") or None,
    )


def _result_to_queue_payload(result, mapping: dict[int, int]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Результат analyzer → analyze_json + edit_json для очереди."""
    analyze_json = {
        "student_name": result.application.student_name,
        "group": result.application.group,
        "program_code": doc_generator.derive_program(result.application.group),
        "course_year": result.application.course_year,
        "phone": result.application.phone,
        "application_date": result.application.application_date,
        "disciplines": result.application.disciplines,
        "certificates": [
            {k: getattr(c, k) for k in CertOut.model_fields} for c in result.certificates
        ],
        "mapping": {str(k): v for k, v in mapping.items()},
        "errors": result.errors,
        "plan_data": result.application.plan_data or {},
    }
    edit_json = {
        "student": {
            "name": analyze_json.get("student_name", ""),
            "group": analyze_json.get("group", ""),
            "program_code": analyze_json.get("program_code", ""),
            "course_year": analyze_json.get("course_year", ""),
        },
        "disciplines": [
            {
                "name": d,
                "plan_credits": "5",
                "total_hours": "",
                "grade_points": "",
                "compliance": "полное",
                "note": "",
                "final_grade": "",
            }
            for d in (analyze_json.get("disciplines") or [])
        ],
        "certificates": [
            {**c, "_bound": None} for c in (analyze_json.get("certificates") or [])
        ],
    }
    for cert_idx_str, disc_idx in (analyze_json.get("mapping") or {}).items():
        try:
            ci = int(cert_idx_str)
            if 0 <= ci < len(edit_json["certificates"]):
                if 0 <= int(disc_idx) < len(edit_json["disciplines"]):
                    edit_json["certificates"][ci]["_bound"] = int(disc_idx)
        except Exception:
            pass
    return analyze_json, edit_json


def _run_pdf_analysis(pdf_bytes: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    gemini_key, openrouter_key = _env_llm_keys()
    if not (gemini_key or openrouter_key):
        raise RuntimeError(
            "Не задан GEMINI_API_KEY или OPENROUTER_API_KEY (в .env или в форме на главной)"
        )
    result = analyzer.analyze_pdf(
        pdf_bytes,
        gemini_api_key=gemini_key,
        openrouter_api_key=openrouter_key,
    )
    mapping: dict[int, int] = {}
    try:
        mapping = analyzer.suggest_mapping(
            result,
            gemini_api_key=gemini_key,
            openrouter_api_key=openrouter_key,
        )
    except Exception:
        mapping = {}
    return _result_to_queue_payload(result, mapping)


async def _run_pdf_analysis_async(pdf_bytes: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """Запускает синхронный _run_pdf_analysis в пуле потоков, не блокируя event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_pdf_analysis, pdf_bytes)


async def _do_analyze_job(job_id: str, pdf_bytes: bytes, auto_map: bool) -> None:
    """Фоновая задача анализа PDF: результат сохраняется в _analyze_jobs[job_id]."""
    loop = asyncio.get_event_loop()
    try:
        gemini_key, openrouter_key = _env_llm_keys()
        if not (gemini_key or openrouter_key):
            raise RuntimeError("Не задан GEMINI_API_KEY или OPENROUTER_API_KEY")

        result = await loop.run_in_executor(
            None,
            lambda: analyzer.analyze_pdf(
                pdf_bytes,
                gemini_api_key=gemini_key,
                openrouter_api_key=openrouter_key,
            ),
        )

        mapping: dict[int, int] = {}
        if auto_map and result.application.disciplines and result.certificates:
            try:
                mapping = await loop.run_in_executor(
                    None,
                    lambda: analyzer.suggest_mapping(
                        result,
                        gemini_api_key=gemini_key,
                        openrouter_api_key=openrouter_key,
                    ),
                )
            except Exception:
                pass

        response = AnalyzeResponse(
            student_name=result.application.student_name,
            group=result.application.group,
            program_code=doc_generator.derive_program(result.application.group),
            course_year=result.application.course_year,
            phone=result.application.phone,
            application_date=result.application.application_date,
            disciplines=result.application.disciplines,
            certificates=[
                CertOut(**{k: getattr(c, k) for k in CertOut.model_fields})
                for c in result.certificates
            ],
            mapping={str(k): v for k, v in mapping.items()},
            errors=result.errors,
            plan_data=result.application.plan_data or {},
        )
        _analyze_jobs[job_id].update({"status": "done", "result": response.model_dump()})
        log(f"Analyze job {job_id}: готово — {result.application.student_name or '—'}")
        # Если была создана запись в очереди — заполняем её данными анализа
        job_meta = _analyze_jobs.get(job_id, {})
        req_id = job_meta.get("request_id")
        if req_id:
            try:
                queue_analyze, queue_edit = _result_to_queue_payload(result, mapping)
                local_pdf = job_meta.get("local_pdf_path", "")
                if local_pdf:
                    queue_analyze["local_pdf_path"] = local_pdf
                STORE.update_analyze(req_id, queue_analyze)
                STORE.save_edit(req_id, queue_edit)
                row = STORE.reset_pending(req_id)
                _broadcast_sse({"type": "updated", **_row_to_sse_dict(row)})
            except Exception as _qe:
                log(f"Analyze job {job_id}: ошибка обновления очереди #{req_id} — {_qe}")
    except Exception as e:
        log(f"Analyze job {job_id}: ошибка — {e}")
        _analyze_jobs[job_id].update({"status": "error", "error": str(e)})
        req_id = _analyze_jobs.get(job_id, {}).get("request_id")
        if req_id:
            try:
                row = STORE.mark_error(req_id, str(e))
                _broadcast_sse({"type": "updated", **_row_to_sse_dict(row)})
            except Exception:
                pass


@app.post("/api/analyze")
async def analyze_submit(
    pdf: UploadFile = File(...),
    auto_map: bool = Form(True),
):
    """Принимает PDF, немедленно возвращает job_id, анализ идёт в фоне."""
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Файл должен быть .pdf")
    pdf_bytes = await pdf.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Пустой PDF")
    job_id = uuid.uuid4().hex[:10]

    # Сохраняем PDF локально и создаём запись в очереди
    upload_id = uuid.uuid4().hex[:12]
    local_pdf_path = APPLICATIONS_DIR / f"upload_{upload_id}.pdf"
    request_id: int | None = None
    try:
        local_pdf_path.write_bytes(pdf_bytes)
        safe_filename = (pdf.filename or f"upload_{upload_id}.pdf")
        row = STORE.upsert_pending(
            drive_file_id=f"upload_{upload_id}",
            filename=safe_filename,
            analyze_json={
                "student_name": "", "group": "", "program_code": "", "course_year": "",
                "phone": "", "application_date": "", "disciplines": [], "certificates": [],
                "mapping": {}, "errors": [], "plan_data": {},
                "local_pdf_path": str(local_pdf_path),
            },
            status="analyzing",
        )
        request_id = row.id
        _broadcast_sse({"type": "added", **_row_to_sse_dict(row)})
        log(f"API /analyze: PDF сохранён → {local_pdf_path}, queue #{request_id}")
    except Exception as _ex:
        log(f"API /analyze: не удалось создать запись в очереди — {_ex}")

    _analyze_jobs[job_id] = {
        "status": "running",
        "result": None,
        "error": None,
        "started_at": time.time(),
        "request_id": request_id,
        "local_pdf_path": str(local_pdf_path) if request_id else None,
    }
    asyncio.create_task(_do_analyze_job(job_id, pdf_bytes, bool(auto_map)))
    log(f"API /analyze: job {job_id} запущен, PDF {len(pdf_bytes)} байт")
    return {"job_id": job_id, "request_id": request_id}


@app.get("/api/analyze/jobs/{job_id}")
async def analyze_job_status(job_id: str):
    """Статус и результат задачи анализа PDF."""
    job = _analyze_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    elapsed = round(time.time() - job.get("started_at", time.time()), 1)
    return {
        "status": job["status"],
        "result": job.get("result"),
        "error": job.get("error"),
        "elapsed": elapsed,
        "request_id": job.get("request_id"),
    }


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    log(f"API /generate: {req.student_name or '—'}, строк таблицы={len(req.rows)}")
    payload = doc_generator.ReportPayload(
        student_name=req.student_name,
        program_code=req.program_code,
        course_year=req.course_year,
        rows=[
            doc_generator.DisciplineRow(
                discipline=r.discipline,
                plan_credits=r.plan_credits,
                total_hours=r.total_hours,
                grade_points=r.grade_points,
                compliance=r.compliance or "полное",
                note=r.note,
                final_grade=r.final_grade,
                courses=[
                    doc_generator.CourseEntry(
                        course_title=c.course_title,
                        provider=c.provider,
                        hours=c.hours,
                        grade=c.grade,
                        date=c.date,
                    )
                    for c in r.courses
                ],
            )
            for r in req.rows
        ],
    )
    data = doc_generator.build_report(payload)
    safe_name = re.sub(r"[^\w\-]+", "_", req.student_name) or "report"
    filename = f"Заключение_{safe_name}.docx"
    log(f"API /generate: DOCX {len(data)} байт → «{filename}»")
    encoded_filename = urllib.parse.quote(filename)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="report.docx"; filename*=utf-8\'\'{encoded_filename}',
        },
    )


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "providers": analyzer.PROVIDER_ORDER,
        "has_gemini_key": bool(os.environ.get("GEMINI_API_KEY")),
        "has_openrouter_key": bool(os.environ.get("OPENROUTER_API_KEY")),
        "gemini_model": analyzer.GEMINI_MODEL,
        "openrouter_models": analyzer.OPENROUTER_MODELS,
        "queue_pending": len(STORE.list(status="pending_approval", limit=500)),
    }


# Статика и индекс
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/approve")
async def approve_page():
    return FileResponse(str(STATIC_DIR / "approve.html"))


@app.get("/api/queue/stream")
async def queue_sse_stream():
    """SSE: пушит обновления статусов очереди всем подключённым клиентам."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_clients.append(q)

    async def event_gen():
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=20.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"type":"heartbeat"}\n\n'
        except asyncio.CancelledError:
            pass
        finally:
            try:
                _sse_clients.remove(q)
            except ValueError:
                pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/requests", response_model=QueueListResponse)
async def list_requests():
    rows = STORE.list(limit=300)
    log(f"API /requests: список ({len(rows)} записей)")
    items: list[QueueListItem] = []
    for r in rows:
        a = r.analyze_json or {}
        items.append(
            QueueListItem(
                id=r.id,
                drive_file_id=r.drive_file_id,
                filename=r.filename,
                status=r.status,
                student_name=a.get("student_name") or "",
                group=a.get("group") or "",
                faculty=a.get("faculty") or "",
                department=a.get("department") or "",
                created_at=r.created_at,
                updated_at=r.updated_at,
                drive_file_url=drive_file_view_url(r.drive_file_id),
                output_drive_file_id=r.output_drive_file_id or "",
                error=r.error or "",
            )
        )
    return QueueListResponse(items=items)


@app.get("/api/requests/{request_id}")
async def get_request(request_id: int):
    try:
        r = STORE.get(int(request_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    log(f"API /requests/{request_id}: статус={r.status}, файл=«{r.filename}»")
    return {
        "id": r.id,
        "status": r.status,
        "filename": r.filename,
        "drive_file_id": r.drive_file_id,
        "drive_file_url": drive_file_view_url(r.drive_file_id),
        "analyze": r.analyze_json,
        "edit": r.edit_json,
        "output_drive_file_id": r.output_drive_file_id,
        "error": r.error,
    }


@app.delete("/api/requests/{request_id}")
async def delete_request(request_id: int):
    try:
        STORE.get(int(request_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    STORE.delete(int(request_id))
    log(f"API /requests/{request_id}: удалён")
    return {"ok": True}


@app.post("/api/requests/{request_id}/edit")
async def save_request_edit(request_id: int, payload: QueueEditState):
    log(f"API /requests/{request_id}/edit: сохранение черновика")
    try:
        r = STORE.save_edit(int(request_id), payload.model_dump())
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "id": r.id, "updated_at": r.updated_at}


@app.post("/api/requests/{request_id}/reanalyze")
async def reanalyze_request(request_id: int):
    """Повторно распознать локальный PDF (заявление + сертификаты)."""
    log(f"API /requests/{request_id}/reanalyze: старт")
    try:
        r = STORE.get(int(request_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    if r.status == "sent":
        raise HTTPException(
            status_code=400,
            detail="Заявление уже отправлено в Drive — повторное распознавание недоступно",
        )

    # Получаем PDF: для intake-заявлений берём локальный файл или Drive-ссылку из metadata
    pdf_bytes: bytes = b""
    meta = r.analyze_json or {}

    if r.drive_file_id.startswith("intake_"):
        intake_app_id = meta.get("intake_app_id")
        # 1) Локальный combined PDF (сохранён при генерации)
        if intake_app_id:
            local_pdf = APPLICATIONS_DIR / f"{intake_app_id}_combined.pdf"
            if local_pdf.is_file():
                try:
                    pdf_bytes = local_pdf.read_bytes()
                    log(f"API /requests/{request_id}/reanalyze: читаем локальный combined PDF")
                except Exception:
                    pdf_bytes = b""
        if not pdf_bytes:
            raise HTTPException(
                status_code=400,
                detail="Файл заявления не найден. Убедитесь, что документ был сформирован через форму /intake.",
            )
    elif r.drive_file_id.startswith("upload_"):
        local_pdf_str = meta.get("local_pdf_path", "")
        if local_pdf_str and Path(local_pdf_str).is_file():
            try:
                pdf_bytes = Path(local_pdf_str).read_bytes()
                log(f"API /requests/{request_id}/reanalyze: читаем локальный upload PDF")
            except Exception:
                pdf_bytes = b""
        if not pdf_bytes:
            raise HTTPException(
                status_code=400,
                detail="Исходный PDF не найден на сервере.",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Повторное распознавание недоступно для этого заявления.",
        )

    r = STORE.mark_analyzing(r.id)
    _broadcast_sse({"type": "updated", **_row_to_sse_dict(r)})
    try:
        log(f"API /requests/{request_id}/reanalyze: распознавание ({len(pdf_bytes)} байт)…")
        analyze_json, edit_json = await _run_pdf_analysis_async(pdf_bytes)
        # Сохраняем специфичные поля если они были в исходном analyze_json
        for key in ("intake_app_id", "intake_drive_pdf_id", "faculty", "department", "local_pdf_path"):
            if meta.get(key) is not None and not analyze_json.get(key):
                analyze_json[key] = meta[key]
        STORE.update_analyze(r.id, analyze_json)
        STORE.save_edit(r.id, edit_json)
        r = STORE.reset_pending(r.id)
        _broadcast_sse({"type": "updated", **_row_to_sse_dict(r)})
        log(f"API /requests/{request_id}/reanalyze: готово")
        return {
            "ok": True,
            "id": r.id,
            "status": r.status,
            "analyze": analyze_json,
            "edit": edit_json,
            "errors": analyze_json.get("errors") or [],
        }
    except HTTPException:
        raise
    except Exception as e:
        log(f"API /requests/{request_id}/reanalyze: ошибка — {e}")
        log(traceback.format_exc().rstrip())
        r = STORE.mark_error(r.id, str(e))
        _broadcast_sse({"type": "updated", **_row_to_sse_dict(r)})
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/requests/{request_id}/approve")
async def approve_request(request_id: int):
    log(f"API /requests/{request_id}/approve: старт")
    try:
        r = STORE.get(int(request_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    if r.status not in ("pending_approval", "approved", "error", "sent"):
        raise HTTPException(status_code=400, detail=f"bad status: {r.status}")

    edit = r.edit_json or {}
    plan_data_for_report = (r.analyze_json or {}).get("plan_data") or {}
    student = edit.get("student") or {}
    disciplines = edit.get("disciplines") or []
    certificates = edit.get("certificates") or []

    def _rows() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for i, d in enumerate(disciplines):
            rows.append(
                {
                    "discipline": d.get("name", ""),
                    "plan_credits": d.get("plan_credits", ""),
                    "total_hours": d.get("total_hours", ""),
                    "grade_points": d.get("grade_points", ""),
                    "compliance": d.get("compliance", "полное"),
                    "note": d.get("note", ""),
                    "final_grade": d.get("final_grade", ""),
                    "courses": [
                        {
                            "course_title": c.get("course_title", ""),
                            "provider": c.get("provider", ""),
                            "hours": c.get("hours", ""),
                            "grade": c.get("grade", ""),
                            "date": c.get("date", ""),
                        }
                        for c in certificates
                        if c.get("_bound", None) == i
                    ],
                }
            )
        return rows

    gen_req = GenerateRequest(
        student_name=str(student.get("name") or ""),
        program_code=str(student.get("program_code") or ""),
        course_year=str(student.get("course_year") or ""),
        rows=[RowIn(**row) for row in _rows()],
    )

    try:
        r = STORE.mark_approved(r.id)
        _broadcast_sse({"type": "updated", **_row_to_sse_dict(r)})
        log(f"API /requests/{request_id}/approve: генерация DOCX…")
        payload = doc_generator.ReportPayload(
            student_name=gen_req.student_name,
            program_code=gen_req.program_code,
            course_year=gen_req.course_year,
            rows=[
                doc_generator.DisciplineRow(
                    discipline=rr.discipline,
                    plan_credits=rr.plan_credits,
                    total_hours=rr.total_hours,
                    grade_points=rr.grade_points,
                    compliance=rr.compliance or "полное",
                    note=rr.note,
                    final_grade=rr.final_grade,
                    courses=[
                        doc_generator.CourseEntry(
                            course_title=c.course_title,
                            provider=c.provider,
                            hours=c.hours,
                            grade=c.grade,
                            date=c.date,
                        )
                        for c in rr.courses
                    ],
                )
                for rr in gen_req.rows
            ],
        )
        data = doc_generator.build_report(payload, plan_data=plan_data_for_report or None)
        safe_name = re.sub(r"[^\w\-]+", "_", gen_req.student_name) or f"request_{r.id}"
        filename = f"Заключение_{safe_name}.docx"

        # Сохранить локально всегда
        local_path = CONCLUSIONS_DIR / filename
        local_path.write_bytes(data)
        log(f"API /requests/{request_id}/approve: DOCX сохранён локально → {local_path}")

        r = STORE.mark_sent(r.id, output_drive_file_id=None, local_file_path=str(local_path))
        _broadcast_sse({"type": "updated", **_row_to_sse_dict(r)})
        log(f"API /requests/{request_id}/approve: успех")
        return {"ok": True, "local_file": filename}
    except Exception as e:
        log(f"API /requests/{request_id}/approve: ошибка — {e}")
        r = STORE.mark_error(r.id, str(e))
        _broadcast_sse({"type": "updated", **_row_to_sse_dict(r)})
        raise HTTPException(status_code=500, detail=str(e))






# ---------------------------------------------------------------------------
# Intake (student application) module
# ---------------------------------------------------------------------------
@app.get("/intake")
async def intake_page():
    return FileResponse(str(STATIC_DIR / "intake.html"))


@app.get("/applications")
async def applications_page():
    return FileResponse(str(STATIC_DIR / "applications.html"))


@app.get("/api/intake/applications")
async def list_intake_applications():
    INTAKE_STORE.sync_from_queue(STORE)
    apps = INTAKE_STORE.list(limit=300)
    return {
        "items": [
            {
                "id": a.id,
                "student_name": a.student_name,
                "faculty": a.faculty,
                "department": a.department,
                "group_name": a.group_name,
                "course_year": a.course_year,
                "phone": a.phone,
                "subjects": a.subjects,
                "status": a.status,
                "drive_pdf_id": a.drive_pdf_id or "",
                "queue_request_id": a.queue_request_id,
                "output_drive_file_id": a.output_drive_file_id or "",
                "created_at": a.created_at,
                "updated_at": a.updated_at,
            }
            for a in apps
        ]
    }


@app.get("/api/intake/applications/{app_id}")
async def get_intake_application(app_id: int):
    try:
        a = INTAKE_STORE.get(int(app_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    INTAKE_STORE.sync_from_queue(STORE)
    a = INTAKE_STORE.get(int(app_id))
    return {
        "id": a.id,
        "student_name": a.student_name,
        "faculty": a.faculty,
        "department": a.department,
        "group_name": a.group_name,
        "course_year": a.course_year,
        "phone": a.phone,
        "subjects": a.subjects,
        "status": a.status,
        "drive_pdf_id": a.drive_pdf_id or "",
        "queue_request_id": a.queue_request_id,
        "output_drive_file_id": a.output_drive_file_id or "",
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


@app.get("/api/intake/applications/{app_id}/pdf")
async def serve_intake_pdf(app_id: int):
    path = APPLICATIONS_DIR / f"{app_id}_combined.pdf"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="PDF не найден")
    encoded = urllib.parse.quote(f"application_{app_id}.pdf")
    return FileResponse(
        str(path),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded}"},
    )


async def _analyze_intake_pdf_bg(
    queue_row_id: int,
    drive_pdf_id: str,
    intake_app_id: int,
    faculty: str,
    department: str,
) -> None:
    """Фоновой LLM-анализ PDF сертификатов для обогащения данных у эксперта."""
    pdf_bytes: bytes = b""

    # Пробуем взять локальный combined PDF (сохранён при генерации)
    local_pdf = APPLICATIONS_DIR / f"{intake_app_id}_combined.pdf"
    if local_pdf.is_file():
        try:
            pdf_bytes = local_pdf.read_bytes()
            log(f"Фоновой анализ intake PDF queue#{queue_row_id}: читаем локальный файл")
        except Exception:
            pdf_bytes = b""

    if not pdf_bytes:
        log(f"Фоновой анализ intake PDF queue#{queue_row_id}: нет PDF — пропускаем")
        return

    try:
        llm_analyze, llm_edit = await _run_pdf_analysis_async(pdf_bytes)
        llm_analyze["intake_app_id"] = intake_app_id
        llm_analyze["faculty"] = faculty
        llm_analyze["department"] = department
        if llm_analyze.get("certificates"):
            STORE.update_analyze(queue_row_id, llm_analyze)
            STORE.save_edit(queue_row_id, llm_edit)
            log(f"Фоновой анализ intake PDF queue#{queue_row_id}: OK, сертификатов={len(llm_analyze['certificates'])}")
        else:
            log(f"Фоновой анализ intake PDF queue#{queue_row_id}: LLM не нашёл сертификатов — оставляем базовые данные")
        row = STORE.reset_pending(queue_row_id)
        _broadcast_sse({"type": "updated", **_row_to_sse_dict(row)})
    except Exception as e:
        log(f"Фоновой анализ intake PDF queue#{queue_row_id}: ошибка LLM — {e}")
        try:
            row = STORE.mark_error(queue_row_id, str(e))
            _broadcast_sse({"type": "updated", **_row_to_sse_dict(row)})
        except Exception:
            pass


@app.post("/api/intake/applications/{app_id}/send-to-review")
async def send_intake_to_review(app_id: int):
    try:
        a = INTAKE_STORE.get(int(app_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    if a.status != "created":
        raise HTTPException(status_code=400, detail=f"Нельзя отправить: статус '{a.status}'")

    disciplines = [s.get("name", "") for s in (a.subjects or []) if s.get("name")]
    program_code = doc_generator.derive_program(a.group_name)

    # Собираем сертификаты из источников, указанных студентом
    certs_analyze: list[dict[str, Any]] = []
    certs_edit: list[dict[str, Any]] = []
    for disc_idx, subj in enumerate(a.subjects or []):
        for cert in (subj.get("certs") or []):
            source = str(cert.get("source") or "").strip()
            if source:
                certs_analyze.append({
                    "page": 0,
                    "course_title": source,
                    "provider": "",
                    "hours": "",
                    "grade": "",
                    "date": "",
                    "student_name": a.student_name,
                    "certificate_id": "",
                    "verify_url": source if source.startswith("http") else "",
                })
                certs_edit.append({
                    "course_title": source,
                    "provider": "",
                    "hours": "",
                    "grade": "",
                    "date": "",
                    "_bound": disc_idx,
                })

    analyze_json: dict[str, Any] = {
        "student_name": a.student_name,
        "group": a.group_name,
        "program_code": program_code,
        "course_year": a.course_year,
        "phone": a.phone,
        "application_date": "",
        "disciplines": disciplines,
        "certificates": certs_analyze,
        "mapping": {str(i): certs_edit[i]["_bound"] for i in range(len(certs_edit))},
        "errors": [],
        "plan_data": {},
        "intake_app_id": a.id,
        "faculty": a.faculty,
        "department": a.department,
        "intake_drive_pdf_id": a.drive_pdf_id or "",
    }
    edit_json: dict[str, Any] = {
        "student": {
            "name": a.student_name,
            "group": a.group_name,
            "program_code": program_code,
            "course_year": a.course_year,
        },
        "disciplines": [
            {
                "name": d,
                "plan_credits": "5",
                "total_hours": "",
                "grade_points": "",
                "compliance": "полное",
                "note": "",
                "final_grade": "",
            }
            for d in disciplines
        ],
        "certificates": certs_edit,
    }

    synthetic_drive_id = f"intake_{a.id}"
    safe_name = re.sub(r"[^\w\-]+", "_", a.student_name) or f"intake_{a.id}"
    filename = f"Заявление_{safe_name}.pdf"

    row = STORE.upsert_pending(
        drive_file_id=synthetic_drive_id,
        filename=filename,
        analyze_json=analyze_json,
        status="analyzing",
    )
    STORE.save_edit(row.id, edit_json)
    INTAKE_STORE.send_to_review(a.id, row.id)
    log(f"API /intake/applications/{app_id}/send-to-review: queue #{row.id}, сертификатов={len(certs_edit)}")
    _broadcast_sse({"type": "added", **_row_to_sse_dict(row)})

    # Фоновой LLM-анализ PDF сертификатов для обогащения данных у эксперта
    _local_pdf_check = APPLICATIONS_DIR / f"{a.id}_combined.pdf"
    if _local_pdf_check.is_file():
        asyncio.create_task(
            _analyze_intake_pdf_bg(row.id, "", a.id, a.faculty, a.department)
        )

    return {"ok": True, "queue_request_id": row.id}


@app.post("/api/intake/generate")
async def intake_generate(request: Request):
    form = await request.form()
    data_json = form.get("data") or "{}"
    try:
        payload_dict = json.loads(data_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Невалидный JSON в поле data")

    raw_subjects = payload_dict.get("subjects") or []
    subjects_list = []
    for s in raw_subjects:
        if isinstance(s, dict):
            name = str(s.get("name") or "").strip()
            certs_raw = s.get("certs") or []
            sources = [str(c.get("source") or "").strip() for c in certs_raw if str(c.get("source") or "").strip()]
        else:
            name = str(s).strip()
            sources = []
        if name:
            subjects_list.append(application_generator.SubjectEntry(name=name, cert_sources=sources))

    p = application_generator.ApplicationPayload(
        student_name=str(payload_dict.get("student_name") or ""),
        faculty=str(payload_dict.get("faculty") or ""),
        department=str(payload_dict.get("department") or ""),
        group=str(payload_dict.get("group") or ""),
        course_year=str(payload_dict.get("course_year") or ""),
        phone=str(payload_dict.get("phone") or ""),
        date=str(payload_dict.get("date") or ""),
        subjects=subjects_list,
    )

    log(f"API /intake/generate: «{p.student_name}», предметов={len(p.subjects)}")

    subjects_for_store = []
    for i, s in enumerate(subjects_list):
        raw = raw_subjects[i] if i < len(raw_subjects) else {}
        raw_dict = raw if isinstance(raw, dict) else {"name": raw}
        subjects_for_store.append({
            "name": s.name,
            "certs": [{"source": src} for src in s.cert_sources],
            "faculty": str(raw_dict.get("faculty") or ""),
            "department": str(raw_dict.get("department") or ""),
        })

    docx_bytes = application_generator.build_application_docx(p)

    # Collect certificate files: keys are cert_{subj_idx}_{cert_idx}
    cert_bytes_map: dict[tuple[int, int], bytes] = {}
    cert_names_map: dict[tuple[int, int], str] = {}
    for field_name, field_value in form.multi_items():
        if field_name.startswith("cert_"):
            try:
                parts = field_name[5:].split("_")
                si, ci = int(parts[0]), int(parts[1])
                content = await field_value.read()
                if content:
                    cert_bytes_map[(si, ci)] = content
                    cert_names_map[(si, ci)] = getattr(field_value, "filename", "") or ""
            except Exception:
                pass

    # Flatten certs in subject/cert order; also build per-subject groups
    cert_list: list[bytes] = []
    cert_fnames: list[str] = []
    cert_groups: list[list[bytes]] = []
    for si, subj in enumerate(p.subjects):
        group: list[bytes] = []
        n_certs = len((raw_subjects[si].get("certs") or [])) if si < len(raw_subjects) and isinstance(raw_subjects[si], dict) else 1
        for ci in range(n_certs):
            b = cert_bytes_map.get((si, ci), b"")
            if b:
                cert_list.append(b)
                cert_fnames.append(cert_names_map.get((si, ci), ""))
                group.append(b)
        cert_groups.append(group)

    # Save intake application to local store
    intake_app = INTAKE_STORE.create(
        student_name=p.student_name,
        faculty=p.faculty,
        department=p.department,
        group_name=p.group,
        course_year=p.course_year,
        phone=p.phone,
        subjects=subjects_for_store,
    )

    # Save DOCX locally
    _app_safe = re.sub(r"[^\w\-]+", "_", p.student_name) or f"app_{intake_app.id}"
    _local_docx = APPLICATIONS_DIR / f"Заявление_{intake_app.id}_{_app_safe}.docx"
    try:
        _local_docx.write_bytes(docx_bytes)
        INTAKE_STORE.set_local_docx(intake_app.id, str(_local_docx))
        log(f"API /intake/generate: DOCX сохранён локально → {_local_docx}")
    except Exception as _ex:
        log(f"API /intake/generate: не удалось сохранить DOCX — {_ex}")

    # Строим combined PDF (заявление + сертификаты)
    combined_pdf: bytes = b""
    try:
        app_pdf = application_generator.build_application_pdf_page(p)
        combined_pdf = application_generator.build_combined_pdf(
            app_pdf, cert_list, payload=p, cert_groups=cert_groups, cert_filenames=cert_fnames
        )
        log(f"API /intake/generate: combined PDF {len(combined_pdf)} байт, страниц сертификатов={len(cert_list)}")
    except Exception as _pdf_ex:
        log(f"API /intake/generate: ошибка сборки PDF — {_pdf_ex}")

    # Сохраняем combined PDF локально
    if combined_pdf:
        _local_pdf = APPLICATIONS_DIR / f"{intake_app.id}_combined.pdf"
        try:
            _local_pdf.write_bytes(combined_pdf)
            log(f"API /intake/generate: combined PDF сохранён → {_local_pdf}")
        except Exception as _ex:
            log(f"API /intake/generate: не удалось сохранить combined PDF — {_ex}")

    safe_name = re.sub(r"[^\w\-]+", "_", p.student_name) or "Заявление"
    docx_filename = f"Заявление_{safe_name}.docx"
    encoded = urllib.parse.quote(docx_filename)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="application.docx"; filename*=utf-8\'\'{encoded}'},
    )


@app.get("/conclusions")
async def conclusions_page():
    return FileResponse(str(STATIC_DIR / "conclusions.html"))


@app.get("/api/conclusions")
async def list_conclusions():
    rows = STORE.list(status="sent", limit=300)
    return {
        "items": [
            {
                "id": r.id,
                "filename": r.filename,
                "student_name": (r.analyze_json or {}).get("student_name") or "",
                "group": (r.analyze_json or {}).get("group") or "",
                "faculty": (r.analyze_json or {}).get("faculty") or "",
                "department": (r.analyze_json or {}).get("department") or "",
                "output_drive_file_id": r.output_drive_file_id or "",
                "local_file_path": r.local_file_path or "",
                "has_local_file": bool(r.local_file_path and Path(r.local_file_path).is_file()),
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]
    }


@app.get("/api/conclusions/{request_id}/download")
async def download_conclusion(request_id: int):
    try:
        r = STORE.get(int(request_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    if not r.local_file_path:
        raise HTTPException(status_code=404, detail="Файл не сохранён локально")
    local_path = Path(r.local_file_path)
    if not local_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден на диске")
    encoded = urllib.parse.quote(local_path.name)
    return FileResponse(
        str(local_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="conclusion.docx"; filename*=utf-8\'\'{encoded}'},
    )


@app.get("/api/requests/{request_id}/pdf")
async def serve_request_pdf(request_id: int):
    try:
        r = STORE.get(int(request_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    local_path_str = (r.analyze_json or {}).get("local_pdf_path", "")
    if not local_path_str:
        raise HTTPException(status_code=404, detail="PDF не найден")
    local_path = Path(local_path_str)
    if not local_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден на диске")
    encoded = urllib.parse.quote(local_path.name)
    return FileResponse(
        str(local_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded}"},
    )


@app.get("/api/applications/{app_id}/download")
async def download_application_docx(app_id: int):
    try:
        a = INTAKE_STORE.get(int(app_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    if not a.local_docx_path:
        raise HTTPException(status_code=404, detail="Файл не сохранён локально")
    local_path = Path(a.local_docx_path)
    if not local_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден на диске")
    encoded = urllib.parse.quote(local_path.name)
    return FileResponse(
        str(local_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="application.docx"; filename*=utf-8\'\'{encoded}'},
    )


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------
_ADMIN_USER = "admin"
_ADMIN_PASS_HASH = "04501b8754661491e7a537b1d724e664c9a8b25605dc8e6d31b0472dc7079290"
_admin_sessions: dict[str, int] = {}
_ADMIN_TTL = 8 * 3600


def _admin_ok(token: str | None) -> bool:
    if not token:
        return False
    exp = _admin_sessions.get(token)
    if exp is None or int(time.time()) > exp:
        _admin_sessions.pop(token, None)
        return False
    return True


def _require_admin(admin_token: str | None = Cookie(None)) -> str:
    if not _admin_ok(admin_token):
        raise HTTPException(status_code=401, detail="Не авторизован")
    return admin_token  # type: ignore[return-value]


class AdminStatusBody(BaseModel):
    status: str
    delete_queue: bool = False


@app.get("/admin")
async def admin_page():
    return FileResponse(str(STATIC_DIR / "admin.html"))


@app.post("/admin/login")
async def admin_login(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
):
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    if username != _ADMIN_USER or pw_hash != _ADMIN_PASS_HASH:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = secrets.token_hex(32)
    _admin_sessions[token] = int(time.time()) + _ADMIN_TTL
    response.set_cookie("admin_token", token, httponly=True, max_age=_ADMIN_TTL, samesite="strict")
    return {"ok": True}


@app.post("/admin/logout")
async def admin_logout(response: Response, _: str = Depends(_require_admin)):
    response.delete_cookie("admin_token")
    return {"ok": True}


@app.get("/admin/api/me")
async def admin_me(admin_token: str | None = Cookie(None)):
    return {"logged_in": _admin_ok(admin_token)}


@app.get("/admin/api/apps")
async def admin_list_apps(_: str = Depends(_require_admin)):
    INTAKE_STORE.sync_from_queue(STORE)
    apps = INTAKE_STORE.list(limit=500)
    return {
        "items": [
            {
                "id": a.id,
                "student_name": a.student_name,
                "faculty": a.faculty,
                "department": a.department,
                "group_name": a.group_name,
                "course_year": a.course_year,
                "status": a.status,
                "drive_pdf_id": a.drive_pdf_id or "",
                "queue_request_id": a.queue_request_id,
                "output_drive_file_id": a.output_drive_file_id or "",
                "created_at": a.created_at,
                "updated_at": a.updated_at,
            }
            for a in apps
        ]
    }


@app.post("/admin/api/apps/{app_id}/status")
async def admin_set_status(
    app_id: int,
    body: AdminStatusBody,
    _: str = Depends(_require_admin),
):
    allowed = ("created", "in_review", "done")
    if body.status not in allowed:
        raise HTTPException(status_code=400, detail=f"Статус должен быть одним из: {allowed}")
    try:
        a = INTAKE_STORE.get(int(app_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")

    old_queue_id = a.queue_request_id
    INTAKE_STORE.reset_status(int(app_id), body.status)

    if body.delete_queue and old_queue_id:
        try:
            STORE.delete(int(old_queue_id))
            log(f"Admin: удалена запись очереди #{old_queue_id} при сбросе заявления #{app_id}")
        except Exception:
            pass

    log(f"Admin: заявление #{app_id} → {body.status}")
    return {"ok": True}


@app.get("/admin/api/queue")
async def admin_list_queue(_: str = Depends(_require_admin)):
    rows = STORE.list(limit=500)
    return {
        "items": [
            {
                "id": r.id,
                "filename": r.filename,
                "drive_file_id": r.drive_file_id,
                "status": r.status,
                "student_name": (r.analyze_json or {}).get("student_name") or "",
                "intake_app_id": (r.analyze_json or {}).get("intake_app_id"),
                "error": r.error or "",
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]
    }


@app.delete("/admin/api/queue/{request_id}")
async def admin_delete_queue(request_id: int, _: str = Depends(_require_admin)):
    try:
        STORE.get(int(request_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    STORE.delete(int(request_id))
    log(f"Admin: удалена запись очереди #{request_id}")
    return {"ok": True}


@app.on_event("startup")
async def _startup() -> None:
    log("========== Старт приложения ==========")
    log(
        f"Конфиг: GEMINI_KEY={'✓' if os.environ.get('GEMINI_API_KEY') else '—'}, "
        f"OPENROUTER_KEY={'✓' if os.environ.get('OPENROUTER_API_KEY') else '—'}"
    )
