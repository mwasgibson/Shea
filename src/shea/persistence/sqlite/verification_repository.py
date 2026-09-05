from __future__ import annotations

import sqlite3

from shea.contracts.models import VerificationRecord

from .unit_of_work import SqliteUnitOfWork


class SqliteVerificationRepository:
    def __init__(self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save(self, record: VerificationRecord) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO verifications (
                    id, task_id, verified, method, explanation, observed_state, 
                    expected_state, confidence, side_effect_detected, retry_safe
                    )
                VALUES (
                    :id, :task_id, :verified, :method, :explanation, :observed_state, 
                    :expected_state, :confidence, :side_effect_detected, :retry_safe
                    )
                """,
                {
                    "id": record.id,
                    "task_id": record.task_id,
                    "verified": int(record.verified),
                    "method": record.method,
                    "explanation": record.explanation,
                    "observed_state": record.observed_state,
                    "expected_state": record.expected_state,
                    "confidence": record.confidence,
                    "side_effect_detected": int(record.side_effect_detected),
                    "retry_safe": int(record.retry_safe),
                },
            )

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
        observed_state=row["observed_state"],
        expected_state=row["expected_state"],
        confidence=row["confidence"],
        side_effect_detected=bool(row["side_effect_detected"]),
        retry_safe=bool(row["retry_safe"]),
    )