from __future__ import annotations

import sqlite3
from datetime import datetime

from shea.app.enums import AppOutcome, IdempotencyState
from shea.app.idempotency import IdempotencyRecord
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


class SqliteAppIdempotencyRepository:
    def __init__(
        self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork
    ) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def get(self, key: str) -> IdempotencyRecord | None:
        row = self._conn.execute(
            "SELECT * FROM app_idempotency WHERE key = ?",
            (key,),
        ).fetchone()
        return _row_to_idempotency(row) if row is not None else None

    def save(self, record: IdempotencyRecord) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO app_idempotency (
                    key, receipt_id, state, outcome, created_at, updated_at
                ) VALUES (
                    :key, :receipt_id, :state, :outcome, :created_at, :updated_at
                )
                ON CONFLICT(key) DO UPDATE SET
                    receipt_id = excluded.receipt_id,
                    state = excluded.state,
                    outcome = excluded.outcome,
                    updated_at = excluded.updated_at
                """,
                {
                    "key": record.key,
                    "receipt_id": record.receipt_id,
                    "state": record.state.value,
                    "outcome": record.outcome.value if record.outcome else None,
                    "created_at": record.created_at.isoformat(),
                    "updated_at": record.updated_at.isoformat(),
                },
            )

    def reserve(self, record: IdempotencyRecord) -> None:
        """Atomically claim a key; the UNIQUE constraint arbitrates races."""
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO app_idempotency (
                    key, receipt_id, state, outcome, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.key,
                    record.receipt_id,
                    record.state.value,
                    record.outcome.value if record.outcome else None,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )


def _row_to_idempotency(row: sqlite3.Row) -> IdempotencyRecord:
    return IdempotencyRecord(
        key=row["key"],
        receipt_id=row["receipt_id"],
        state=IdempotencyState(row["state"]),
        outcome=AppOutcome(row["outcome"]) if row["outcome"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )