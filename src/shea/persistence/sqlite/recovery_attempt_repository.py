from __future__ import annotations

import sqlite3

from shea.contracts.models import RecoveryAttempt


class SqliteRecoveryAttemptRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, attempt: RecoveryAttempt) -> None:
        self._conn.execute(
            """
            INSERT INTO recovery_attempts
                (id, task_id, attempt_number, resolved, recovered, method, explanation)
            VALUES
                (:id, :task_id, :attempt_number, :resolved, :recovered, :method, :explanation)
            ON CONFLICT(id) DO UPDATE SET
                resolved = excluded.resolved,
                recovered = excluded.recovered,
                method = excluded.method,
                explanation = excluded.explanation
            """,
            {
                "id": attempt.id,
                "task_id": attempt.task_id,
                "attempt_number": attempt.attempt_number,
                "resolved": int(attempt.resolved),
                "recovered": None if attempt.recovered is None else int(attempt.recovered),
                "method": attempt.method,
                "explanation": attempt.explanation,
            },
        )
        self._conn.commit()

    def list_by_task(self, task_id: str) -> list[RecoveryAttempt]:
        rows = self._conn.execute(
            "SELECT * FROM recovery_attempts WHERE task_id = ? ORDER BY attempt_number",
            (task_id,),
        ).fetchall()
        return [_row_to_attempt(row) for row in rows]

    def get_latest_by_task(self, task_id: str) -> RecoveryAttempt | None:
        row = self._conn.execute(
            """
            SELECT * FROM recovery_attempts
            WHERE task_id = ? ORDER BY attempt_number DESC LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        return _row_to_attempt(row) if row is not None else None


def _row_to_attempt(row: sqlite3.Row) -> RecoveryAttempt:
    recovered = row["recovered"]
    return RecoveryAttempt(
        id=row["id"],
        task_id=row["task_id"],
        attempt_number=row["attempt_number"],
        resolved=bool(row["resolved"]),
        recovered=None if recovered is None else bool(recovered),
        method=row["method"],
        explanation=row["explanation"],
    )