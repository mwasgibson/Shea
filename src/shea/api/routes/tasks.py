from __future__ import annotations

import sqlite3
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from shea.api.contracts import TaskView
from shea.bootstrap import SheaRuntime
from shea.contracts.enums import TaskState

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def get_runtime(request: Request) -> SheaRuntime:
    return cast(SheaRuntime, request.app.state.runtime)


def _row_to_view(row: sqlite3.Row) -> TaskView:
    return TaskView(
        id=row["id"],
        session_id=row["session_id"],
        request_id=row["request_id"],
        state=row["state"],
        plan_id=row["plan_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/", response_model=list[TaskView])
async def list_tasks(
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
    session_id: str | None = None,
    state: str | None = None,
    limit: int = Query(50, le=500),
) -> list[TaskView]:
    """List tasks from the shared SQLite source of truth (observer)."""
    conn: sqlite3.Connection = runtime.conn
    clauses: list[str] = []
    params: list[Any] = []

    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if state:
        try:
            TaskState(state)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid state: {state}") from exc
        clauses.append("state = ?")
        params.append(state)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM tasks {where} ORDER BY updated_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_view(row) for row in rows]


@router.get("/{task_id}", response_model=TaskView)
async def get_task(
    task_id: str,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> TaskView:
    row = runtime.conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _row_to_view(row)