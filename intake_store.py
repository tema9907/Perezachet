"""Local SQLite store for intake applications."""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from syslog import log

IntakeStatus = Literal["created", "in_review", "done"]


@dataclass(frozen=True)
class IntakeApp:
    id: int
    student_name: str
    faculty: str
    department: str
    group_name: str
    course_year: str
    phone: str
    subjects: list[dict]
    status: str
    drive_pdf_id: str | None
    local_docx_path: str | None
    queue_request_id: int | None
    output_drive_file_id: str | None
    created_at: int
    updated_at: int


class IntakeStore:
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
                CREATE TABLE IF NOT EXISTS intake_applications (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_name          TEXT NOT NULL DEFAULT '',
                    faculty               TEXT NOT NULL DEFAULT '',
                    department            TEXT NOT NULL DEFAULT '',
                    group_name            TEXT NOT NULL DEFAULT '',
                    course_year           TEXT NOT NULL DEFAULT '',
                    phone                 TEXT NOT NULL DEFAULT '',
                    subjects_json         TEXT NOT NULL DEFAULT '[]',
                    status                TEXT NOT NULL DEFAULT 'created',
                    drive_pdf_id          TEXT NULL,
                    local_docx_path       TEXT NULL,
                    queue_request_id      INTEGER NULL,
                    output_drive_file_id  TEXT NULL,
                    created_at            INTEGER NOT NULL,
                    updated_at            INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_intake_status "
                "ON intake_applications(status)"
            )
            # Safe migration for existing databases
            try:
                conn.execute("ALTER TABLE intake_applications ADD COLUMN local_docx_path TEXT NULL")
            except sqlite3.OperationalError:
                pass  # column already exists
        log(f"IntakeStore: БД {self.db_path}")

    def _row(self, r: sqlite3.Row) -> IntakeApp:
        return IntakeApp(
            id=int(r["id"]),
            student_name=str(r["student_name"]),
            faculty=str(r["faculty"]),
            department=str(r["department"]),
            group_name=str(r["group_name"]),
            course_year=str(r["course_year"]),
            phone=str(r["phone"]),
            subjects=json.loads(r["subjects_json"]),
            status=str(r["status"]),
            drive_pdf_id=str(r["drive_pdf_id"]) if r["drive_pdf_id"] else None,
            local_docx_path=str(r["local_docx_path"]) if r["local_docx_path"] else None,
            queue_request_id=int(r["queue_request_id"]) if r["queue_request_id"] else None,
            output_drive_file_id=str(r["output_drive_file_id"]) if r["output_drive_file_id"] else None,
            created_at=int(r["created_at"]),
            updated_at=int(r["updated_at"]),
        )

    def create(
        self,
        *,
        student_name: str,
        faculty: str,
        department: str,
        group_name: str,
        course_year: str,
        phone: str,
        subjects: list[dict[str, Any]],
        drive_pdf_id: str | None = None,
    ) -> IntakeApp:
        now = int(time.time())
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO intake_applications
                    (student_name, faculty, department, group_name, course_year, phone,
                     subjects_json, status, drive_pdf_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'created', ?, ?, ?)
                """,
                (
                    student_name, faculty, department, group_name, course_year, phone,
                    json.dumps(subjects, ensure_ascii=False), drive_pdf_id, now, now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM intake_applications WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            assert row is not None
            app = self._row(row)
            log(f"IntakeStore: создано заявление #{app.id} «{student_name}»")
            return app

    def list(self, limit: int = 300) -> list[IntakeApp]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM intake_applications ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, app_id: int) -> IntakeApp:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM intake_applications WHERE id = ?", (int(app_id),)
            ).fetchone()
        if not row:
            raise KeyError(f"intake application {app_id} not found")
        return self._row(row)

    def set_local_docx(self, app_id: int, local_docx_path: str) -> IntakeApp:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "UPDATE intake_applications SET local_docx_path = ?, updated_at = ? WHERE id = ?",
                (local_docx_path, now, int(app_id)),
            )
            row = conn.execute(
                "SELECT * FROM intake_applications WHERE id = ?", (int(app_id),)
            ).fetchone()
            assert row is not None
            return self._row(row)

    def set_drive_pdf(self, app_id: int, drive_pdf_id: str) -> IntakeApp:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "UPDATE intake_applications SET drive_pdf_id = ?, updated_at = ? WHERE id = ?",
                (drive_pdf_id, now, int(app_id)),
            )
            row = conn.execute(
                "SELECT * FROM intake_applications WHERE id = ?", (int(app_id),)
            ).fetchone()
            assert row is not None
            return self._row(row)

    def send_to_review(self, app_id: int, queue_request_id: int) -> IntakeApp:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE intake_applications
                SET status = 'in_review', queue_request_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (queue_request_id, now, int(app_id)),
            )
            row = conn.execute(
                "SELECT * FROM intake_applications WHERE id = ?", (int(app_id),)
            ).fetchone()
            assert row is not None
            app = self._row(row)
            log(f"IntakeStore: #{app_id} → in_review (queue #{queue_request_id})")
            return app

    def mark_done(self, app_id: int, output_drive_file_id: str) -> IntakeApp:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE intake_applications
                SET status = 'done', output_drive_file_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (output_drive_file_id, now, int(app_id)),
            )
            row = conn.execute(
                "SELECT * FROM intake_applications WHERE id = ?", (int(app_id),)
            ).fetchone()
            assert row is not None
            app = self._row(row)
            log(f"IntakeStore: #{app_id} → done (drive_out={output_drive_file_id})")
            return app

    def reset_status(self, app_id: int, new_status: str) -> IntakeApp:
        """Admin: принудительно сменить статус, очистить связанные поля."""
        now = int(time.time())
        with self._connect() as conn:
            if new_status == "created":
                conn.execute(
                    """UPDATE intake_applications
                       SET status='created', queue_request_id=NULL,
                           output_drive_file_id=NULL, updated_at=?
                       WHERE id=?""",
                    (now, int(app_id)),
                )
            elif new_status == "in_review":
                conn.execute(
                    """UPDATE intake_applications
                       SET status='in_review', output_drive_file_id=NULL, updated_at=?
                       WHERE id=?""",
                    (now, int(app_id)),
                )
            else:
                conn.execute(
                    "UPDATE intake_applications SET status=?, updated_at=? WHERE id=?",
                    (new_status, now, int(app_id)),
                )
            row = conn.execute(
                "SELECT * FROM intake_applications WHERE id=?", (int(app_id),)
            ).fetchone()
            assert row is not None
            app = self._row(row)
            log(f"IntakeStore: #{app_id} → {new_status} (admin reset)")
            return app

    def sync_from_queue(self, queue_store: Any) -> None:
        """Pull status updates from QueueStore for in_review applications."""
        apps = [a for a in self.list() if a.status == "in_review" and a.queue_request_id]
        for app in apps:
            try:
                req = queue_store.get(app.queue_request_id)
                if req.status == "sent" and req.output_drive_file_id:
                    self.mark_done(app.id, req.output_drive_file_id)
            except KeyError:
                pass
