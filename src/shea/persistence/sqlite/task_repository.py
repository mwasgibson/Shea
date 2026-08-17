from __future__ import annotations

import sqlite3
from datetime import datetime

from shea.contracts.enums import TaskState
from shea.contracts.models import Task


class SqliteTaskRepository:
    """Concrete adapter for the TaskRepository port (shea.ports.repositories).

    Implements the Protocol structurally — no inheritance needed, but the
    method signatures must match exactly.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, task: Task) -> None:
        self._conn.execute(
            """
            INSERT INTO tasks (id, session_id, request_id, state, plan_id, created_at, updated_at)
            VALUES (:id, :session_id, :request_id, :state, :plan_id, :created_at, :updated_at)
            ON CONFLICT(id) DO UPDATE SET
                state = excluded.state,
                plan_id = excluded.plan_id,
                updated_at = excluded.updated_at
            """,
            {
                "id": task.id,
                "session_id": task.session_id,
                "request_id": task.request_id,
                "state": task.state.value,
                "plan_id": task.plan_id,
                "created_at": task.created_at.isoformat(),
                "updated_at": task.updated_at.isoformat(),
            },
        )
        self._conn.commit()

    def get(self, task_id: str) -> Task | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_task(row)

    def list_by_session(self, session_id: str) -> list[Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [_row_to_task(row) for row in rows]


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        session_id=row["session_id"],
        request_id=row["request_id"],
        state=TaskState(row["state"]),
        plan_id=row["plan_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )