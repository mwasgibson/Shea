from __future__ import annotations

import sqlite3
from datetime import datetime

from shea.contracts.enums import TaskState
from shea.contracts.models import Task

from .unit_of_work import SqliteUnitOfWork


class SqliteTaskRepository:
    """Concrete adapter for the TaskRepository port (shea.ports.repositories).

    Implements the Protocol structurally — no inheritance needed, but the
    method signatures must match exactly.
    """

    def __init__(self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save(self, task: Task) -> None:
        import json
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO tasks
                    (id, session_id, request_id, state, plan_id, profile_snapshot, created_at, updated_at)
                VALUES
                    (:id, :session_id, :request_id, :state, :plan_id, :profile_snapshot, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    state = excluded.state,
                    plan_id = excluded.plan_id,
                    profile_snapshot = excluded.profile_snapshot,
                    updated_at = excluded.updated_at
                """,
                {
                    "id": task.id,
                    "session_id": task.session_id,
                    "request_id": task.request_id,
                    "state": task.state.value,
                    "plan_id": task.plan_id,
                    "profile_snapshot": json.dumps(task.profile_snapshot) if task.profile_snapshot else None,
                    "created_at": task.created_at.isoformat(),
                    "updated_at": task.updated_at.isoformat(),
                },
            )

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


    def list_transient_tasks(self) -> list[Task]:
        # Stable states: COMPLETED, CANCELLED, SECURITY_HALT (terminal)
        # and FAILED, BLOCKED (requiring explicit resolution)
        stable_states = ("COMPLETED", "CANCELLED", "SECURITY_HALT", "FAILED", "BLOCKED")
        placeholders = ",".join("?" for _ in stable_states)
        rows = self._conn.execute(
            f"SELECT * FROM tasks WHERE state NOT IN ({placeholders}) ORDER BY created_at",
            stable_states,
        ).fetchall()
        return [_row_to_task(row) for row in rows]

def _row_to_task(row: sqlite3.Row) -> Task:
    import json
    
    raw_snapshot = row["profile_snapshot"] if "profile_snapshot" in row.keys() else None
    snapshot = json.loads(raw_snapshot) if raw_snapshot else None
    
    return Task(
        id=row["id"],
        session_id=row["session_id"],
        request_id=row["request_id"],
        state=TaskState(row["state"]),
        plan_id=row["plan_id"],
        profile_snapshot=snapshot,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )