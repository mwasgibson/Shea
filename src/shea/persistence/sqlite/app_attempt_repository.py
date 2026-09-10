from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from shea.app.contracts import ExecutionAttempt
from shea.app.enums import AppOutcome, AttemptState
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class SqliteAppAttemptRepository:
    def __init__(
        self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork
    ) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save(self, attempt: ExecutionAttempt) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO app_attempts (
                    id, receipt_id, attempt_number, state, created_at,
                    invoked_at, finalized_at, outcome, adapter_name,
                    error, evidence
                ) VALUES (
                    :id, :receipt_id, :attempt_number, :state, :created_at,
                    :invoked_at, :finalized_at, :outcome, :adapter_name,
                    :error, :evidence
                )
                ON CONFLICT(id) DO UPDATE SET
                    state = excluded.state,
                    invoked_at = excluded.invoked_at,
                    finalized_at = excluded.finalized_at,
                    outcome = excluded.outcome,
                    adapter_name = excluded.adapter_name,
                    error = excluded.error,
                    evidence = excluded.evidence
                """,
                {
                    "id": attempt.id,
                    "receipt_id": attempt.receipt_id,
                    "attempt_number": attempt.attempt_number,
                    "state": attempt.state.value,
                    "created_at": attempt.created_at.isoformat(),
                    "invoked_at": (
                        attempt.invoked_at.isoformat()
                        if attempt.invoked_at
                        else None
                    ),
                    "finalized_at": (
                        attempt.finalized_at.isoformat()
                        if attempt.finalized_at
                        else None
                    ),
                    "outcome": attempt.outcome.value if attempt.outcome else None,
                    "adapter_name": attempt.adapter_name,
                    "error": attempt.error,
                    "evidence": json.dumps(attempt.evidence),
                },
            )

    def list_by_receipt(self, receipt_id: str) -> list[ExecutionAttempt]:
        rows = self._conn.execute(
            """
            SELECT * FROM app_attempts
            WHERE receipt_id = ?
            ORDER BY attempt_number ASC, rowid ASC
            """,
            (receipt_id,),
        ).fetchall()
        return [_row_to_attempt(row) for row in rows]


def _row_to_attempt(row: sqlite3.Row) -> ExecutionAttempt:
    evidence: dict[str, Any] = json.loads(row["evidence"] or "{}")
    return ExecutionAttempt(
        id=row["id"],
        receipt_id=row["receipt_id"],
        attempt_number=int(row["attempt_number"]),
        state=AttemptState(row["state"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        invoked_at=_parse_dt(row["invoked_at"]),
        finalized_at=_parse_dt(row["finalized_at"]),
        outcome=AppOutcome(row["outcome"]) if row["outcome"] else None,
        adapter_name=row["adapter_name"],
        error=row["error"],
        evidence=evidence,
    )