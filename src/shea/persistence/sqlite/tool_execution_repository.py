from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from shea.contracts.enums import ExecutionOutcome
from shea.contracts.models import ToolExecutionRecord


def _serialize_data(data: Any) -> str | None:
    if data is None:
        return None
    try:
        return json.dumps(data)
    except TypeError:
        # Best-effort fallback for non-JSON-serializable tool data — the
        # record is still readable, just not round-trippable to the
        # original Python type.
        return json.dumps(str(data))


class SqliteToolExecutionRepository:
    """Insert-only: a task may accumulate multiple execution records
    across retries, each a fact about what actually happened, never
    overwritten.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, record: ToolExecutionRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO tool_executions
                (
                    id, task_id, tool, action, outcome, success, data, error, 
                    attempt_number, idempotency_key, started_at, finished_at, metadata
                )
            VALUES
                (
                    :id, :task_id, :tool, :action, :outcome, :success, :data, 
                    :error, :attempt_number, :idempotency_key, :started_at, :finished_at, :metadata
                )
            ON CONFLICT(id) DO UPDATE SET
                outcome = excluded.outcome,
                success = excluded.success,
                data = excluded.data,
                error = excluded.error,
                attempt_number = excluded.attempt_number,
                idempotency_key = excluded.idempotency_key,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                metadata = excluded.metadata    
            """,
            {
                "id": record.id,
                "task_id": record.task_id,
                "tool": record.tool,
                "action": record.action,
                "outcome": record.outcome.value,
                "success": int(record.success),
                "data": _serialize_data(record.data),
                "error": record.error,
                "attempt_number": int(record.attempt_number),
                "idempotency_key": record.idempotency_key,
                "started_at": (
                    record.started_at.isoformat()
                    if record.started_at
                    else None
                ),
                "finished_at": (
                    record.finished_at.isoformat()
                    if record.finished_at
                    else None
                ),
                "metadata": _serialize_data(record.metadata),
            },
        )
        self._conn.commit()

    def list_by_task(self, task_id: str) -> list[ToolExecutionRecord]:
        rows = self._conn.execute(
            "SELECT * FROM tool_executions WHERE task_id = ? ORDER BY rowid",
            (task_id,),
        ).fetchall()
        return [_row_to_record(row) for row in rows]

    def get_latest_by_task(self, task_id: str) -> ToolExecutionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM tool_executions WHERE task_id = ? ORDER BY rowid DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return _row_to_record(row) if row is not None else None


def _row_to_record(row: sqlite3.Row) -> ToolExecutionRecord:

    return ToolExecutionRecord(
        id=row["id"],
        task_id=row["task_id"],
        tool=row["tool"],
        action=row["action"],
        outcome=ExecutionOutcome(row["outcome"]),
        success=bool(row["success"]),
        data=json.loads(row["data"]) if row["data"] is not None else None,
        error=row["error"],
        attempt_number=int(row["attempt_number"]),
        idempotency_key=row["idempotency_key"],
        started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        metadata=json.loads(row["metadata"]) if row["metadata"] is not None else {},
    )