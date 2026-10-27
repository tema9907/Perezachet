"""LLM-логика модуля формального перезачёта (Gemini + OpenRouter fallback).

Три задачи:
  1. analyze_formal_pdf() — PDF (стр.1 заявление + далее транскрипт) → ФИО, вуз-источник,
     программа-источник, список дисциплин транскрипта с оценками.
  2. parse_pasted_plan() — текст учебного плана, вставленный экспертом (когда сайт вуза
     упал), → структурированный список дисциплин с кредитами.
  3. match_plan_to_transcript() — сопоставляет дисциплины целевого плана с транскриптом.

Переиспользует vision-провайдеров из analyzer.py; для текстовых задач ходит в Gemini
напрямую (google.genai), с лёгким OpenRouter-fallback.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import analyzer
from syslog import log

try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except ImportError:  # pragma: no cover
    _HAS_FITZ = False

try:
    from google import genai
    from google.genai import types as genai_types
    _HAS_GEMINI = True
except ImportError:  # pragma: no cover
    _HAS_GEMINI = False

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
# DPI рендера сканов для vision (150 мало для плотных таблиц; 300 читается уверенно)
SCAN_DPI = int(os.environ.get("FORMAL_SCAN_DPI", "300"))
# JPEG вместо PNG: тот же пиксельный размер, но ~6× меньше байт (15 МБ → 2.5 МБ на
# 2 страницах) — именно загрузка картинок, а не сам инференс, съедала основное время.
SCAN_JPEG_QUALITY = int(os.environ.get("FORMAL_SCAN_JPEG_QUALITY", "80"))
# DPI дешёвой пробы ориентации (нужно только «читается/не читается»)
PROBE_DPI = int(os.environ.get("FORMAL_PROBE_DPI", "110"))
# Повороты для перебора (сканы часто отсканированы боком)
SCAN_ROTATIONS = (0, 90, 180, 270)
# Транскрипты техникумов доходят до 100+ дисциплин — на 16k ответ обрывался по
# MAX_TOKENS, модель уходила в цикл, и запускался бесполезный перебор поворотов.
MAX_OUT_TOKENS = int(os.environ.get("FORMAL_MAX_OUT_TOKENS", "32000"))
# Сколько страниц распознаём и сколько параллельных вызовов держим
MAX_PAGES = int(os.environ.get("FORMAL_MAX_PAGES", "8"))
MAX_PARALLEL = int(os.environ.get("FORMAL_MAX_PARALLEL", "4"))
# Объём в учебном плане СКУ задан в кредитах, в транскриптах колледжей — в часах.
# Пересчёт для сравнения объёмов: 1 кредит ≈ 15 академических часов.
HOURS_PER_CREDIT = float(os.environ.get("FORMAL_HOURS_PER_CREDIT", "15"))


def to_number(v: Any) -> float | None:
    """'216', '4,5', '72 ч.' → число; мусор → None."""
    m = re.search(r"\d+(?:[.,]\d+)?", str(v or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def credits_to_hours(credits: Any) -> float | None:
    c = to_number(credits)
    return None if c is None else c * HOURS_PER_CREDIT


def fmt_number(v: float | None) -> str:
    """Число → строка без хвостового '.0' (часы обычно целые)."""
    if v is None:
        return ""
    return str(int(round(v))) if abs(v - round(v)) < 0.05 else f"{v:.1f}".replace(".", ",")


def _parallel(fns: list[Any]) -> list[Any]:
    """Выполняет список thunk'ов параллельно; исключения → None."""
    if not fns:
        return []
    if len(fns) == 1:
        try:
            return [fns[0]()]
        except Exception as e:
            log(f"formal_analyzer: задача упала — {str(e)[:120]}")
            return [None]

    def _safe(fn: Any) -> Any:
        try:
            return fn()
        except Exception as e:
            log(f"formal_analyzer: задача упала — {str(e)[:120]}")
            return None

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(fns))) as pool:
        return list(pool.map(_safe, fns))


# ---------------------------------------------------------------------------
# Низкоуровневые вызовы LLM
# ---------------------------------------------------------------------------
_CLIENTS: dict[str, Any] = {}
# Общий потолок одновременных запросов к Gemini: постраничные вызовы идут из
# вложенных пулов (повороты × страницы), а квота у ключа одна на всех.
_GEMINI_SEM = threading.BoundedSemaphore(MAX_PARALLEL)


def _client(key: str) -> Any:
    """genai.Client переиспользуем: создание клиента заново на каждый вызов
    заставляло пересоздавать HTTP-пул и TLS-соединение."""
    c = _CLIENTS.get(key)
    if c is None:
        c = _CLIENTS[key] = genai.Client(api_key=key)
    return c


def _retrying(fn: Any, *, attempts: int = 3) -> Any:
    """Повтор при временных ошибках (429/503): при параллельных вызовах в них
    легко упереться, а потеря страницы = потеря дисциплин в заключении."""
    delay = 3.0
    for i in range(attempts):
        try:
            return fn()
        except analyzer.TransientError as e:
            if i == attempts - 1:
                raise
            log(f"formal_analyzer: временная ошибка ({str(e)[:60]}), "
                f"повтор через {delay:.0f}s")
            time.sleep(delay)
            delay *= 2.5
    return None
def _salvage_json(text: str) -> dict[str, Any]:
    """Из частично-оборванного JSON вытаскивает скалярные поля и ЗАВЕРШЁННЫЕ записи transcript."""
    out: dict[str, Any] = {}
    for f in ("student_name", "source_institution", "source_program"):
        m = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % f, text)
        if m:
            out[f] = m.group(1)
    tm = re.search(r'"transcript"\s*:\s*\[', text)
    if tm:
        items: list[Any] = []
        depth = 0
        buf = ""
        started = False
        for ch in text[tm.end():]:
            if ch == "{":
                depth += 1
                started = True
            if started:
                buf += ch
            if ch == "}":
                depth -= 1
                if depth == 0 and buf.strip():
                    try:
                        items.append(json.loads(buf))
                    except ValueError:
                        pass
                    buf = ""
                    started = False
            elif ch == "]" and depth == 0:
                break
        if items:
            out["transcript"] = items
    return out


def _gemini_generate(parts: list[Any], *, gemini_key: str | None,
                     max_output_tokens: int = MAX_OUT_TOKENS) -> dict[str, Any]:
    """Один вызов Gemini с произвольными частями (текст и/или картинки) → JSON."""
    key = gemini_key or os.environ.get("GEMINI_API_KEY")
    if not (_HAS_GEMINI and key):
        raise analyzer.QuotaError("Gemini недоступен (нет ключа/пакета)")
    client = _client(key)
    cfg_kwargs: dict[str, Any] = dict(
        response_mime_type="application/json",
        temperature=0.1,
        max_output_tokens=max_output_tokens,  # плотные таблицы дают длинный JSON
    )
    # Отключаем «thinking» — иначе gemini-2.5-flash тратит выходные токены на рассуждения
    # и обрывает ответ по MAX_TOKENS (особенно на коротких лимитах). Быстрее и стабильнее.
    try:
        cfg_kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass
    try:
        with _GEMINI_SEM:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=genai_types.GenerateContentConfig(**cfg_kwargs),
            )
        raw = resp.text or ""
        truncated = False
        try:
            truncated = "MAX_TOKENS" in str(resp.candidates[0].finish_reason)
        except Exception:
            pass
        try:
            data = analyzer._extract_json(raw)
        except Exception:
            data = {}
        # при обрыве / пустом парсе — спасаем завершённые записи из частичного JSON
        if truncated or not data:
            salv = _salvage_json(raw)
            if len(salv.get("transcript") or []) > len(data.get("transcript") or []):
                if truncated:
                    log(f"formal_analyzer: ⚠ обрыв (MAX_TOKENS) — спасено записей: "
                        f"{len(salv.get('transcript') or [])}")
                data = salv
        if isinstance(data, dict):
            data["_truncated"] = truncated  # признак обрыва (для выбора ориентации)
        return data
    except Exception as e:  # классифицируем как в analyzer.GeminiProvider
        msg = str(e)
        if "PerDay" in msg or "RequestsPerDay" in msg:
            raise analyzer.QuotaError(msg[:200]) from e
        if any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
            raise analyzer.TransientError(msg[:200]) from e
        raise


def _gemini_text_json(prompt: str, *, gemini_key: str | None,
                      images: list[bytes] | None = None,
                      max_output_tokens: int = MAX_OUT_TOKENS,
                      mime: str = "image/jpeg") -> dict[str, Any]:
    parts: list[Any] = []
    for img in images or []:
        parts.append(genai_types.Part.from_bytes(data=img, mime_type=mime))
    parts.append(prompt)
    return _gemini_generate(parts, gemini_key=gemini_key, max_output_tokens=max_output_tokens)


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------
def _extract_text(pdf_bytes: bytes) -> str:
    if not _HAS_FITZ:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return ""
    chunks = []
    for i, page in enumerate(doc):
        chunks.append(f"\n===== СТРАНИЦА {i + 1} =====\n" + page.get_text("text"))
    doc.close()
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# 1. Разбор PDF заявления+транскрипта
# ---------------------------------------------------------------------------
_TRANSCRIPT_PROMPT = """Ты — ассистент приёмной комиссии университета. Тебе дают PDF студента для
признания результатов обучения. В документе ЕСТЬ ТРАНСКРИПТ (таблица изученных дисциплин с оценками),
и МОЖЕТ быть заявление о признании.

ВАЖНО про порядок страниц: он ЛЮБОЙ. Заявление может быть первой страницей, а может ОТСУТСТВОВАТЬ —
тогда документ начинается сразу с транскрипта. Транскриптов может быть несколько. Сам определи,
какая страница — заявление, а какая — транскрипт, и работай с транскриптом(ами).

Извлеки данные и верни СТРОГО JSON:
{
  "student_name": "ФИО студента полностью (как в транскрипте)",
  "source_institution": "название вуза, где студент учился ранее (из транскрипта/заявления)",
  "source_program": "код и название специальности-источника, напр. 6B06111 «Информационные системы в управлении»",
  "transcript": [
    {
      "name": "название дисциплины на русском",
      "code": "код дисциплины из транскрипта (если есть)",
      "hours": "объём в ЧАСАХ (число) — если в документе есть колонка часов",
      "credits": "объём в КРЕДИТАХ (число) — только если в документе указаны именно кредиты",
      "grade_points": "балл (число, напр. 68)",
      "grade_letter": "буквенная оценка (напр. C, A-, B+)",
      "grade_traditional": "традиционная оценка если есть"
    }
  ]
}

Правила:
- Дисциплины бери ТОЛЬКО из транскрипта (страницу-заявление для списка дисциплин игнорируй).
- Если заявления нет — ФИО/вуз/специальность-источник бери из транскрипта.
- В transcript включай ВСЕ дисциплины, практики и госэкзамены из транскрипта(ов).
- Названия дисциплин — на РУССКОМ (в транскрипте они обычно двуязычные kz/ru — бери русский вариант).
- Оценку "балл(буква)" разбивай: grade_points="68", grade_letter="C".

ОБЪЁМ ДИСЦИПЛИНЫ — ВАЖНО:
- Нам нужны ЧАСЫ. В приложениях к дипломам колледжей/техникумов объём почти всегда
  указан в ЧАСАХ (обычно десятки-сотни: 24, 48, 72, 216) — это и есть "hours".
- Если в таблице ДВЕ колонки объёма (и кредиты, и часы) — в "hours" клади часы,
  в "credits" кредиты. Не путай их местами: часы — заметно большее число.
- Если колонка объёма ОДНА, реши по величине и заголовку, что это: часы (тогда
  заполни только "hours") или кредиты (тогда только "credits"). Пересчёт сделаем сами.
- Не выдумывай: если объёма в документе нет — обе строки пустые.
- Если поля нет — пустая строка "". Никакого текста вне JSON."""


def _classify_page(text: str) -> str:
    """Грубо определяет тип страницы по ключевым словам."""
    low = (text or "").lower()
    tr_markers = ("транскрипт", "the transcript", "наименование дисциплины", "gpa",
                  "год поступления", "кол-во кредитов", "əрiптiк", "буквенная")
    ap_markers = ("заявление", "прошу вас признать", "председателю комиссии",
                  "согласен на использование", "зав. кафедрой", "дата заявления")
    tr = sum(m in low for m in tr_markers)
    ap = sum(m in low for m in ap_markers)
    if tr > ap and tr:
        return "транскрипт"
    if ap > tr and ap:
        return "заявление"
    return "иное"


def _pages_structure_hint(text: str) -> str:
    """Строит подсказку «Страница N — тип» из размеченного текста (===== СТРАНИЦА N =====)."""
    parts = re.split(r"=====\s*СТРАНИЦА\s+(\d+)\s*=====", text)
    # parts = ['', '1', '<txt1>', '2', '<txt2>', ...]
    hints = []
    for i in range(1, len(parts) - 1, 2):
        num = parts[i]
        body = parts[i + 1]
        hints.append(f"страница {num} — {_classify_page(body)}")
    return "; ".join(hints)


def _page_count(pdf_bytes: bytes) -> int:
    if not _HAS_FITZ:
        return 0
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return doc.page_count
    finally:
        doc.close()


def _render_pages(pdf_bytes: bytes, *, dpi: int, rotation: int = 0,
                  pages: list[int] | None = None) -> list[bytes]:
    """Рендер страниц PDF в JPEG с заданным DPI и поворотом (градусы)."""
    if not _HAS_FITZ:
        return []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out: list[bytes] = []
    try:
        for i, page in enumerate(doc):
            if pages is not None and i not in pages:
                continue
            m = fitz.Matrix(dpi / 72, dpi / 72)
            if rotation:
                m = m * fitz.Matrix(rotation)  # fitz.Matrix(deg) — матрица поворота
            pix = page.get_pixmap(matrix=m)
            out.append(pix.tobytes("jpeg", jpg_quality=SCAN_JPEG_QUALITY))
    finally:
        doc.close()
    return out


_PROBE_PROMPT = """Тебе дают 4 варианта ОДНОЙ страницы скана, повёрнутые на 0°, 90°, 180°, 270°
(именно в этом порядке, индексы 0,1,2,3). Определи, в каком варианте текст читается НОРМАЛЬНО:
строки идут горизонтально слева направо, буквы стоят прямо (не на боку и не вверх ногами).
Верни СТРОГО JSON: {"upright_index": <0,1,2 или 3>, "sample_text": "<3-5 слов, прочитанных с этой страницы>"}
Никакого текста вне JSON."""


def _detect_rotation(pdf_bytes: bytes, *, gemini_key: str | None) -> int | None:
    """Один дешёвый вызов (4 маленькие картинки одной страницы) → нужный поворот.

    Раньше ориентацию искали перебором ПОЛНОГО распознавания на четырёх поворотах —
    до 4 тяжёлых вызовов по ~60 с. Проба стоит ~2-3 с и ~1 МБ.
    """
    try:
        variants = [_render_pages(pdf_bytes, dpi=PROBE_DPI, rotation=r, pages=[0])
                    for r in SCAN_ROTATIONS]
    except Exception as e:
        log(f"formal_analyzer: проба ориентации — рендер не удался {str(e)[:80]}")
        return None
    images = [v[0] for v in variants if v]
    if len(images) != len(SCAN_ROTATIONS):
        return None
    try:
        d = _gemini_text_json(_PROBE_PROMPT, gemini_key=gemini_key, images=images,
                              max_output_tokens=200)
    except Exception as e:
        log(f"formal_analyzer: проба ориентации не удалась — {str(e)[:80]}")
        return None
    try:
        idx = int(d.get("upright_index"))
    except (TypeError, ValueError):
        return None
    if not 0 <= idx < len(SCAN_ROTATIONS):
        return None
    rotation = SCAN_ROTATIONS[idx]
    log(f"formal_analyzer: ориентация определена — {rotation}° "
        f"(«{str(d.get('sample_text') or '')[:60]}»)")
    return rotation


def _merge_page_results(results: list[dict[str, Any] | None]) -> dict[str, Any]:
    """Склеивает постраничные результаты в один: реквизиты — первые непустые,
    дисциплины — конкатенация в порядке страниц."""
    out: dict[str, Any] = {"student_name": "", "source_institution": "",
                           "source_program": "", "transcript": []}
    truncated = False
    for d in results:
        if not isinstance(d, dict):
            continue
        truncated = truncated or bool(d.get("_truncated"))
        for k in ("student_name", "source_institution", "source_program"):
            if not out[k] and (d.get(k) or "").strip():
                out[k] = str(d[k]).strip()
        out["transcript"].extend(_normalize_transcript(dict(d)).get("transcript") or [])
    out["_truncated"] = truncated
    return out


def _extract_by_pages(pdf_bytes: bytes, prompt: str, *, rotation: int,
                      gemini_key: str | None) -> dict[str, Any]:
    """Распознаёт КАЖДУЮ страницу отдельным параллельным вызовом и склеивает.

    Так лимит выходных токенов приходится на одну страницу (длинные транскрипты
    техникумов больше не обрываются), а по времени работает самая долгая страница,
    а не их сумма.
    """
    n_pages = min(_page_count(pdf_bytes), MAX_PAGES)
    if n_pages <= 0:
        return {}
    images = _render_pages(pdf_bytes, dpi=SCAN_DPI, rotation=rotation,
                           pages=list(range(n_pages)))
    if not images:
        return {}
    results = _parallel([
        (lambda img=img: _retrying(
            lambda: _gemini_text_json(prompt, gemini_key=gemini_key, images=[img])))
        for img in images
    ])
    merged = _merge_page_results(results)
    log(f"formal_analyzer: vision {SCAN_DPI}dpi {rotation}° — постранично "
        f"{[len((r or {}).get('transcript') or []) for r in results]} → "
        f"{len(merged['transcript'])} дисциплин"
        + (" (ОБРЫВ на какой-то странице)" if merged.get("_truncated") else ""))
    return merged


def _vision_extract(pdf_bytes: bytes, prompt: str, *,
                    gemini_key: str | None) -> dict[str, Any]:
    """Vision-распознавание скана: проба ориентации → постраничное распознавание.

    Если проба не сработала или ничего не нашлось — откатываемся на перебор поворотов,
    но уже ПАРАЛЛЕЛЬНО (время ≈ одного вызова, а не четырёх подряд). Признак верной
    ориентации прежний: извлечение завершилось БЕЗ обрыва (на неверной модель «плывёт»
    и уходит в MAX_TOKENS, порождая фейковые строки), поэтому чистый результат
    предпочитаем самому длинному.
    """
    rotation = _detect_rotation(pdf_bytes, gemini_key=gemini_key)
    if rotation is not None:
        data = _extract_by_pages(pdf_bytes, prompt, rotation=rotation,
                                 gemini_key=gemini_key)
        if data.get("transcript"):
            return data
        log("formal_analyzer: проба дала пустой результат — перебираем повороты")

    others = [r for r in SCAN_ROTATIONS if r != rotation]
    results = _parallel([
        (lambda r=r: (r, _extract_by_pages(pdf_bytes, prompt, rotation=r,
                                           gemini_key=gemini_key)))
        for r in others
    ])
    best_clean: dict[str, Any] = {}
    best_clean_n = -1
    best_any: dict[str, Any] = {}
    best_any_n = -1
    for item in results:
        if not item:
            continue
        r, d = item
        n = len(d.get("transcript") or [])
        truncated = bool(d.get("_truncated"))
        log(f"formal_analyzer: поворот {r}° → {n} дисциплин"
            f"{' (ОБРЕЗАНО)' if truncated else ' (чисто)'}")
        if n > best_any_n:
            best_any, best_any_n = d, n
        if not truncated and n > best_clean_n:
            best_clean, best_clean_n = d, n
    return best_clean if best_clean_n >= 1 else best_any


_TR_FIELDS = ("name", "code", "hours", "credits",
              "grade_points", "grade_letter", "grade_traditional")


def _normalize_transcript(data: dict[str, Any]) -> dict[str, Any]:
    data.setdefault("transcript", [])
    data.setdefault("student_name", "")
    data.setdefault("source_institution", "")
    data.setdefault("source_program", "")
    norm: list[dict[str, Any]] = []
    for d in data.get("transcript") or []:
        if not (isinstance(d, dict) and (d.get("name") or "").strip()):
            continue
        item = {k: ("" if d.get(k) is None else str(d.get(k)).strip()) for k in _TR_FIELDS}
        # Объём приводим к ЧАСАМ: если документ дал только кредиты — пересчитываем.
        hours = to_number(item["hours"])
        if hours is None:
            hours = credits_to_hours(item["credits"])
            if hours is not None:
                item["hours_derived"] = "1"  # признак пересчёта (не из документа)
        item["hours"] = fmt_number(hours)
        norm.append(item)
    data["transcript"] = norm
    return data


def _quality_warnings(data: dict[str, Any]) -> list[str]:
    """Проверки качества распознавания — показываются эксперту как предупреждения."""
    w: list[str] = []
    tr = data.get("transcript") or []
    if not tr:
        w.append("Не распознано ни одной дисциплины — проверьте качество скана "
                 "или заполните вручную.")
    if not (data.get("student_name") or "").strip():
        w.append("Не распознано ФИО студента.")
    if not (data.get("source_program") or "").strip():
        w.append("Не распознана специальность-источник.")
    no_grade = sum(1 for d in tr if not (d.get("grade_points") or d.get("grade_letter")))
    if tr and no_grade:
        w.append(f"У {no_grade} из {len(tr)} дисциплин не распознана оценка — проверьте.")
    no_hours = sum(1 for d in tr if not (d.get("hours") or "").strip())
    if tr and no_hours:
        w.append(f"У {no_hours} из {len(tr)} дисциплин не распознан объём в часах — "
                 f"без него соответствие по объёму не проверить.")
    derived = sum(1 for d in tr if d.get("hours_derived"))
    if derived:
        w.append(f"У {derived} дисциплин часы получены пересчётом из кредитов "
                 f"(×{fmt_number(HOURS_PER_CREDIT)}) — сверьте с документом.")
    return w


def analyze_formal_pdf(pdf_bytes: bytes, *, gemini_key: str | None = None,
                       openrouter_key: str | None = None) -> dict[str, Any]:
    """PDF → {student_name, source_institution, source_program, transcript:[...], warnings:[...]}

    Устойчивость: цифровой PDF читаем по тексту; скан/пустой результат → vision с
    авто-подбором поворота и повышенным DPI. Итог проверяется на полноту (warnings).
    """
    text = _extract_text(pdf_bytes)
    data: dict[str, Any] = {}

    # 1) Цифровой PDF — по встроенному тексту
    if len(text.strip()) >= 200:
        prompt = _TRANSCRIPT_PROMPT
        hint = _pages_structure_hint(text)
        if hint:
            prompt += f"\n\nСтруктура страниц (определена автоматически): {hint}."
            log(f"formal_analyzer: структура страниц — {hint}")
        prompt += "\n\nТЕКСТ ДОКУМЕНТА:\n" + text[:30000]
        try:
            data = _gemini_text_json(prompt, gemini_key=gemini_key)
        except Exception as e:
            log(f"formal_analyzer: текстовый разбор не удался — {str(e)[:80]}")
        data = _normalize_transcript(data)

    # 2) Скан ИЛИ текстовый путь не дал дисциплин → vision с перебором поворота
    if not (data.get("transcript")):
        log("formal_analyzer: переход на vision (скан/пустой текст)")
        vis = _vision_extract(pdf_bytes, _TRANSCRIPT_PROMPT, gemini_key=gemini_key)
        vis = _normalize_transcript(vis)
        # если vision дал больше — используем его; иначе оставляем что было
        if len(vis.get("transcript") or []) >= len(data.get("transcript") or []):
            # не теряем поля, если текст их дал, а vision — нет
            for k in ("student_name", "source_institution", "source_program"):
                if not (vis.get(k) or "").strip() and (data.get(k) or "").strip():
                    vis[k] = data[k]
            data = vis

    data.pop("_truncated", None)  # служебный флаг наружу не отдаём
    data["warnings"] = _quality_warnings(data)
    log(f"formal_analyzer: итог — «{data.get('student_name')}», "
        f"дисциплин={len(data.get('transcript') or [])}, "
        f"предупреждений={len(data['warnings'])}")
    return data


# ---------------------------------------------------------------------------
# 2. Разбор вставленного вручную учебного плана
# ---------------------------------------------------------------------------
_PLAN_PROMPT = """Тебе дают ТЕКСТ учебного плана специальности (скопирован со страницы вуза
или из документа). Извлеки список дисциплин. Верни СТРОГО JSON:
{
  "disciplines": [
    {"name": "название дисциплины на русском", "credits": "кредиты (число)",
     "cycle": "цикл если есть (ООД/БД/ПД)", "code": "шифр если есть"}
  ]
}
Правила:
- Бери только учебные дисциплины и виды работ (включая практики). Пропускай заголовки, итоги, GPA.
- Название — на русском. Если поля нет — "". Никакого текста вне JSON.

ТЕКСТ ПЛАНА:
"""


def parse_pasted_plan(text: str, *, gemini_key: str | None = None,
                      openrouter_key: str | None = None) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    data = _gemini_text_json(_PLAN_PROMPT + text[:30000], gemini_key=gemini_key)
    disciplines = [
        {k: ("" if d.get(k) is None else str(d.get(k)).strip())
         for k in ("name", "credits", "cycle", "code")}
        for d in (data.get("disciplines") or []) if isinstance(d, dict)
    ]
    log(f"formal_analyzer: вставленный план распознан, дисциплин={len(disciplines)}")
    return disciplines


# ---------------------------------------------------------------------------
# 3. Сопоставление план ↔ транскрипт
# ---------------------------------------------------------------------------
_MATCH_PROMPT = """Ты — эксперт по перезачёту дисциплин. Есть два списка:

СПИСОК А — учебный план ЦЕЛЕВОЙ программы нашего вуза (дисциплины, которые студенту
можно перезачесть). Объём указан в КРЕДИТАХ:
{plan}

СПИСОК B — дисциплины из ТРАНСКРИПТА студента (что он реально изучил ранее).
Объём указан в ЧАСАХ:
{transcript}

ПЕРЕСЧЁТ ОБЪЁМА: 1 кредит ≈ {hpc} академических часов. То есть дисциплина плана на
5 кредитов требует примерно {ex5} часов освоенного материала.

Для КАЖДОЙ дисциплины из списка А подбери подходящие дисциплины из списка B по смыслу
(не по точному совпадению названий: «Высшая математика» ↔ «Математика»,
«Введение в профессиональную деятельность» ↔ «Введение в информационные системы» и т.п.).

ВАЖНО: одной дисциплине плана может соответствовать НЕСКОЛЬКО дисциплин транскрипта —
тогда перечисли их все. Так бывает, когда крупная дисциплина плана «собирается» из
нескольких мелких: «Языки и технологии программирования» ← «Основы алгоритмизации и
программирования» + «Программирование» + «Разработка программного кода»;
«Модуль социально-политических знаний» ← «Социология» + «Политология» + «Культурология».

СТРОГИЕ ОГРАНИЧЕНИЯ (нарушение делает заключение недействительным):
- Обычно это 1-3 дисциплины, в редких случаях до 5. Список из десятка дисциплин на одну
  строку плана — заведомо ошибка.
- Включай ТОЛЬКО те дисциплины, чьё содержание прямо соответствует дисциплине плана.
  Родственная тематика («что-то про компьютеры») — недостаточное основание.
- НЕ НАБИРАЙ дисциплины ради часов. Избыточный объём не улучшает соответствие, а вот
  лишняя дисциплина — грубая ошибка. Если часов не хватает — оставь как есть и поставь
  "частичное"; это нормальный и ожидаемый результат.
- Каждую дисциплину транскрипта используй МАКСИМУМ В ОДНОЙ строке плана. Если она
  подходит к нескольким — выбери ту, где соответствие ближе.
- Общеобразовательные и служебные строки транскрипта (GPA, «Итоговая аттестация»,
  «Квалификационный экзамен», производственное обучение без своей темы) не приписывай
  к профильным дисциплинам плана.
- ПУСТО ЛУЧШЕ, ЧЕМ НЕВЕРНО. Если подходящей по содержанию дисциплины в транскрипте нет —
  оставь "transcript_indexes": []. Дисциплина просто уйдёт в академическую разницу, это
  штатный исход. Подобрать «хоть что-то похожее» — ошибка.

ДИСЦИПЛИНЫ С УЗКИМ СООТВЕТСТВИЕМ (частые ошибки, соблюдай буквально):
- «Математика» ← только собственно математика: «Математика», «Высшая математика»,
  «Алгебра», «Геометрия», «Математический анализ». Ничего другого в эту строку не клади.
- Математику НЕЛЬЗЯ приписывать к «Основам экономики, предпринимательства и финансовой
  грамотности» — туда идут только экономические и правовые дисциплины: «Финансовая
  грамотность», «Основы экономики», «Основы предпринимательства», «Основы права»
  и подобные им.
- «Манаштану» / «Историческая персоналистика» ← только «Манаштану», «Манашеведение»
  и прямые варианты этого же названия. История Казахстана, всемирная история, биология
  и любые другие дисциплины сюда НЕ подходят: нет манаштану в транскрипте — оставь пусто.

Поле "compliance" оценивай по ДВУМ признакам сразу:
- по содержанию — покрывают ли выбранные дисциплины цели дисциплины плана;
- по объёму — хватает ли суммы часов выбранных дисциплин на требуемые кредиты.
«полное» — совпадает и содержание, и объёма достаточно; «частичное» — содержание
близкое, но объём заметно меньше требуемого либо покрыта лишь часть тем;
«не соответствует» — содержание не подходит.

Верни СТРОГО JSON:
{{
  "matches": [
    {{"plan_index": <индекс из А, с 0>,
      "transcript_indexes": [<индексы из B>],
      "compliance": "полное" | "частичное" | "не соответствует"}}
  ]
}}
По одной записи на каждую дисциплину плана. Если соответствий нет — "transcript_indexes": [].
Никакого текста вне JSON."""


def _match_indexes(m: dict[str, Any]) -> list[int]:
    """Индексы транскрипта из записи матчинга (новый формат-список и старый скаляр)."""
    raw = m.get("transcript_indexes")
    if raw is None:
        raw = m.get("transcript_index")
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    out: list[int] = []
    for v in raw:
        try:
            i = int(v)
        except (TypeError, ValueError):
            continue
        if i >= 0 and i not in out:
            out.append(i)
    return out


# Больше — почти наверняка модель «добирала часы» количеством, а не по смыслу.
MAX_FACTS_PER_ROW = int(os.environ.get("FORMAL_MAX_FACTS_PER_ROW", "5"))


def _sanitize_matches(matches: list[dict[str, Any]], plan: list[dict[str, Any]]) -> None:
    """Страховка от разросшегося матчинга: дедуп между строками + предел на строку.

    Модель иногда приписывает одну дисциплину транскрипта сразу нескольким строкам плана
    или сваливает в одну строку десяток предметов — в официальном заключении и то и другое
    выглядит как ошибка. Правим на месте, лишнее логируем.
    """
    used: dict[int, int] = {}          # индекс транскрипта → строка плана, где он занят
    for m in matches:
        try:
            pi = int(m.get("plan_index"))
        except (TypeError, ValueError):
            pi = -1
        kept: list[int] = []
        for ti in m.get("transcript_indexes") or []:
            if ti in used:
                log(f"formal_analyzer: дисциплина транскрипта #{ti} уже занята строкой "
                    f"плана #{used[ti]} — из строки #{pi} убрана")
                continue
            if len(kept) >= MAX_FACTS_PER_ROW:
                name = plan[pi].get("name", "") if 0 <= pi < len(plan) else f"#{pi}"
                log(f"formal_analyzer: у «{name[:40]}» больше {MAX_FACTS_PER_ROW} предметов — "
                    f"лишние отброшены (похоже на добор часов количеством)")
                break
            used[ti] = pi
            kept.append(ti)
        m["transcript_indexes"] = kept


def match_plan_to_transcript(plan: list[dict[str, Any]], transcript: list[dict[str, Any]],
                             *, gemini_key: str | None = None,
                             openrouter_key: str | None = None) -> list[dict[str, Any]]:
    if not plan or not transcript:
        return []
    plan_txt = "\n".join(
        f"{i}. {d.get('name','')} — {d.get('credits','')} кр."
        f" (≈{fmt_number(credits_to_hours(d.get('credits')))} ч.)"
        for i, d in enumerate(plan)
    )
    tr_txt = "\n".join(
        f"{i}. {d.get('name','')} — {d.get('hours','') or '?'} ч., оценка "
        f"{d.get('grade_points','')}"
        f"{('('+d.get('grade_letter','')+')') if d.get('grade_letter') else ''}"
        for i, d in enumerate(transcript)
    )
    prompt = _MATCH_PROMPT.format(
        plan=plan_txt, transcript=tr_txt,
        hpc=fmt_number(HOURS_PER_CREDIT), ex5=fmt_number(5 * HOURS_PER_CREDIT))
    data = _gemini_text_json(prompt, gemini_key=gemini_key)
    matches = [m for m in (data.get("matches") or []) if isinstance(m, dict)]
    # нормализуем к списку индексов, чтобы вызывающий код не разбирал два формата
    for m in matches:
        m["transcript_indexes"] = _match_indexes(m)
    _sanitize_matches(matches, plan)
    matched = sum(1 for m in matches if m["transcript_indexes"])
    log(f"formal_analyzer: сопоставление — {matched}/{len(plan)} дисциплин плана "
        f"сопоставлено (предметов транскрипта задействовано: "
        f"{sum(len(m['transcript_indexes']) for m in matches)})")
    return matches
