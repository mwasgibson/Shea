from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from shea.contracts.models import Intent

from .unit_of_work import SqliteUnitOfWork


class SqliteIntentRepository:
    def __init__(self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save(self, intent: Intent) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO intents
                    (id, request_id, type, goal, parameters, confidence, source, created_at)
                VALUES
                    (:id, :request_id, :type, :goal, :parameters, :confidence, :source, :created_at)
                """,
                {
                    "id": intent.id,
                    "request_id": intent.request_id,
                    "type": intent.type,
                    "goal": intent.goal,
                    "parameters": json.dumps(intent.parameters),
                    "confidence": intent.confidence,
                    "source": intent.source,
                    "created_at": (intent.created_at or datetime.now()).isoformat(),
                },
            )

    def get_by_request(self, request_id: str) -> Intent | None:
        row = self._conn.execute(
            "SELECT * FROM intents WHERE request_id = ?", (request_id,)
        ).fetchone()
        return _row_to_intent(row) if row is not None else None

    def get_by_task(self, task_id: str) -> Intent | None:
        """Convenience for callers that only hold a task id: resolves
        Task -> request_id -> Intent."""
        row = self._conn.execute(
            """
            SELECT i.* FROM intents i
            JOIN tasks t ON t.request_id = i.request_id
            WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()
        return _row_to_intent(row) if row is not None else None


def _row_to_intent(row: sqlite3.Row) -> Intent:
    return Intent(
        id=row["id"],
        request_id=row["request_id"],
        type=row["type"],
        goal=row["goal"],
        parameters=json.loads(row["parameters"]),
        confidence=row["confidence"],
        source=row["source"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )