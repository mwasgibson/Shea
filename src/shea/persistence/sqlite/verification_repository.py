from __future__ import annotations

import sqlite3

from shea.contracts.models import VerificationRecord


class SqliteVerificationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, record: VerificationRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO verifications (id, task_id, verified, method, explanation)
            VALUES (:id, :task_id, :verified, :method, :explanation)
            """,
            {
                "id": record.id,
                "task_id": record.task_id,
                "verified": int(record.verified),
                "method": record.method,
                "explanation": record.explanation,
            },
        )
        self._conn.commit()

    def list_by_task(self, task_id: str) -> list[VerificationRecord]:
        rows = self._conn.execute(
            "SELECT * FROM verifications WHERE task_id = ? ORDER BY rowid",
            (task_id,),
        ).fetchall()
        return [_row_to_record(row) for row in rows]

    def get_latest_by_task(self, task_id: str) -> VerificationRecord | None:
        row = self._conn.execute(
            "SELECT * FROM verifications WHERE task_id = ? ORDER BY rowid DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return _row_to_record(row) if row is not None else None


def _row_to_record(row: sqlite3.Row) -> VerificationRecord:
    return VerificationRecord(
        id=row["id"],
        task_id=row["task_id"],
        verified=bool(row["verified"]),
        method=row["method"],
        explanation=row["explanation"],
    )