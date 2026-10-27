"""Local SQLite store for FORMAL education recognition (перезачёт формального обучения).

Хранит заявления на признание результатов формального обучения (студент принёс
транскрипт из другого вуза) и кеш учебных планов, снятых с is.ku.edu.kz.

Динамические данные лежат в JSON-блобах:
  - plan_json     — учебный план целевой программы (список дисциплин с кредитами)
  - analyze_json  — распознанные Gemini данные (заявление + транскрипт)
  - edit_json     — редактируемая экспертом таблица сопоставления
  - meta_json     — реквизиты протокола (номер, дата, комиссия, эксперты, акад. разница)
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from syslog import log

FormalStatus = Literal["created", "analyzing", "pending_approval", "done", "error"]


@dataclass(frozen=True)
class FormalApp:
    id: int
    student_name: str
    source_institution: str
    source_program: str
    target_program: str
    target_faculty: str
    target_speciality: str
    target_stream: str
    target_course: str
    target_year: str
    target_group: str
    status: str
    pdf_path: str | None
    plan_json: dict[str, Any]
    analyze_json: dict[str, Any]
    edit_json: dict[str, Any]
    meta_json: dict[str, Any]
    conclusion_path: str | None
    protocol_path: str | None
    error: str | None
    created_at: int
    updated_at: int


def _j(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


class FormalStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS formal_applications (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_name        TEXT NOT NULL DEFAULT '',
                    source_institution  TEXT NOT NULL DEFAULT '',
                    source_program      TEXT NOT NULL DEFAULT '',
                    target_program      TEXT NOT NULL DEFAULT '',
                    target_faculty      TEXT NOT NULL DEFAULT '',
                    target_speciality   TEXT NOT NULL DEFAULT '',
                    target_stream       TEXT NOT NULL DEFAULT '',
                    target_course       TEXT NOT NULL DEFAULT '',
                    target_year         TEXT NOT NULL DEFAULT '',
                    target_group        TEXT NOT NULL DEFAULT '',
                    status              TEXT NOT NULL DEFAULT 'created',
                    pdf_path            TEXT NULL,
                    plan_json           TEXT NOT NULL DEFAULT '{}',
                    analyze_json        TEXT NOT NULL DEFAULT '{}',
                    edit_json           TEXT NOT NULL DEFAULT '{}',
                    meta_json           TEXT NOT NULL DEFAULT '{}',
                    conclusion_path     TEXT NULL,
                    protocol_path       TEXT NULL,
                    error               TEXT NULL,
                    created_at          INTEGER NOT NULL,
                    updated_at          INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_formal_status "
                "ON formal_applications(status)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS curriculum_cache (
                    cache_key   TEXT PRIMARY KEY,
                    label       TEXT NOT NULL DEFAULT '',
                    plan_json   TEXT NOT NULL DEFAULT '{}',
                    created_at  INTEGER NOT NULL,
                    updated_at  INTEGER NOT NULL
                )
                """
            )
        log(f"FormalStore: БД {self.db_path}")

    def _row(self, r: sqlite3.Row) -> FormalApp:
        return FormalApp(
            id=int(r["id"]),
            student_name=str(r["student_name"]),
            source_institution=str(r["source_institution"]),
            source_program=str(r["source_program"]),
            target_program=str(r["target_program"]),
            target_faculty=str(r["target_faculty"]),
            target_speciality=str(r["target_speciality"]),
            target_stream=str(r["target_stream"]),
            target_course=str(r["target_course"]),
            target_year=str(r["target_year"]),
            target_group=str(r["target_group"]),
            status=str(r["status"]),
            pdf_path=str(r["pdf_path"]) if r["pdf_path"] else None,
            plan_json=_j(r["plan_json"], {}),
            analyze_json=_j(r["analyze_json"], {}),
            edit_json=_j(r["edit_json"], {}),
            meta_json=_j(r["meta_json"], {}),
            conclusion_path=str(r["conclusion_path"]) if r["conclusion_path"] else None,
            protocol_path=str(r["protocol_path"]) if r["protocol_path"] else None,
            error=str(r["error"]) if r["error"] else None,
            created_at=int(r["created_at"]),
            updated_at=int(r["updated_at"]),
        )

    # -- CRUD -----------------------------------------------------------------
    def create(self, *, student_name: str = "", pdf_path: str | None = None,
               target_program: str = "", target_faculty: str = "",
               target_speciality: str = "", target_stream: str = "",
               target_course: str = "", target_year: str = "",
               status: str = "created") -> FormalApp:
        now = int(time.time())
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO formal_applications
                    (student_name, target_program, target_faculty, target_speciality,
                     target_stream, target_course, target_year, status, pdf_path,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (student_name, target_program, target_faculty, target_speciality,
                 target_stream, target_course, target_year, status, pdf_path, now, now),
            )
            row = conn.execute(
                "SELECT * FROM formal_applications WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            assert row is not None
            app = self._row(row)
            log(f"FormalStore: создано заявление #{app.id} «{student_name}»")
            return app

    def list(self, limit: int = 300) -> list[FormalApp]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM formal_applications ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, app_id: int) -> FormalApp:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM formal_applications WHERE id = ?", (int(app_id),)
            ).fetchone()
        if not row:
            raise KeyError(f"formal application {app_id} not found")
        return self._row(row)

    def _update(self, app_id: int, fields: dict[str, Any]) -> FormalApp:
        fields = dict(fields)
        fields["updated_at"] = int(time.time())
        cols = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [int(app_id)]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE formal_applications SET {cols} WHERE id = ?", params
            )
            row = conn.execute(
                "SELECT * FROM formal_applications WHERE id = ?", (int(app_id),)
            ).fetchone()
            assert row is not None
            return self._row(row)

    def save_plan(self, app_id: int, plan: dict[str, Any], *,
                  target: dict[str, Any] | None = None) -> FormalApp:
        fields: dict[str, Any] = {"plan_json": json.dumps(plan, ensure_ascii=False)}
        if target:
            for k in ("target_program", "target_faculty", "target_speciality",
                      "target_stream", "target_course", "target_year", "target_group"):
                if k in target:
                    fields[k] = str(target[k])
        app = self._update(app_id, fields)
        log(f"FormalStore: #{app_id} план сохранён, дисциплин={len(plan.get('disciplines') or [])}")
        return app

    def save_analyze(self, app_id: int, analyze: dict[str, Any]) -> FormalApp:
        fields = {"analyze_json": json.dumps(analyze, ensure_ascii=False)}
        # подтягиваем ключевые поля в колонки
        for col, key in (("student_name", "student_name"),
                         ("source_institution", "source_institution"),
                         ("source_program", "source_program")):
            v = (analyze.get(key) or "").strip()
            if v:
                fields[col] = v
        return self._update(app_id, fields)

    def save_edit(self, app_id: int, edit: dict[str, Any],
                  meta: dict[str, Any] | None = None) -> FormalApp:
        fields = {"edit_json": json.dumps(edit, ensure_ascii=False)}
        if meta is not None:
            fields["meta_json"] = json.dumps(meta, ensure_ascii=False)
        return self._update(app_id, fields)

    def set_status(self, app_id: int, status: str,
                   error: str | None = None) -> FormalApp:
        fields: dict[str, Any] = {"status": status}
        fields["error"] = (error[:2000] if error else None)
        app = self._update(app_id, fields)
        log(f"FormalStore: #{app_id} → {status}" + (f" ({error[:80]})" if error else ""))
        return app

    def set_outputs(self, app_id: int, *, conclusion_path: str | None = None,
                    protocol_path: str | None = None) -> FormalApp:
        fields: dict[str, Any] = {"status": "done"}
        if conclusion_path is not None:
            fields["conclusion_path"] = conclusion_path
        if protocol_path is not None:
            fields["protocol_path"] = protocol_path
        return self._update(app_id, fields)

    def delete(self, app_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM formal_applications WHERE id = ?", (int(app_id),))
        log(f"FormalStore: #{app_id} удалён")

    # -- Curriculum cache -----------------------------------------------------
    def cache_get(self, cache_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT plan_json FROM curriculum_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return _j(row["plan_json"], None) if row else None

    def cache_purge_stale(self, version_prefix: str) -> int:
        """Убирает планы, собранные прошлой версией разбора (ключ с другим префиксом).

        Кеш хранит уже обработанные дисциплины, поэтому после изменения логики
        разбора старые записи — просто мусор, который нельзя отдавать эксперту.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM curriculum_cache WHERE cache_key NOT LIKE ?",
                (version_prefix + "%",),
            )
            n = cur.rowcount or 0
        if n:
            log(f"FormalStore: удалено устаревших планов из кеша: {n}")
        return n

    def cache_put(self, cache_key: str, label: str, plan: dict[str, Any]) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO curriculum_cache (cache_key, label, plan_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    label = excluded.label,
                    plan_json = excluded.plan_json,
                    updated_at = excluded.updated_at
                """,
                (cache_key, label, json.dumps(plan, ensure_ascii=False), now, now),
            )
        log(f"FormalStore: план закеширован «{cache_key}» ({label})")
