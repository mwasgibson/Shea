from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from shea.bootstrap import SheaRuntime
from shea.observability.metrics import MetricSnapshot, global_metrics

router = APIRouter(prefix="/observability", tags=["Observability"])


def get_runtime(request: Request) -> SheaRuntime:
    return cast(SheaRuntime, request.app.state.runtime)


class AuditLogResponse(BaseModel):
    events: list[dict[str, Any]]
    total: int


@router.get("/metrics", response_model=MetricSnapshot)
async def get_metrics() -> MetricSnapshot:
    """Retrieve live operational metrics from the sliding window registry."""
    return global_metrics.get_snapshot()


@router.get("/audit", response_model=AuditLogResponse)
async def get_audit_logs(
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
    limit: int = Query(50, le=1000),
    task_id: str | None = None,
) -> AuditLogResponse:
    """Retrieve audit logs directly from the application database.

    The route intentionally reads from the shared runtime DB connection as an
    observer; it does not mutate the audit trail or depend on private memory-store
    implementation details.
    """
    conn: sqlite3.Connection = runtime.conn

    query = "SELECT * FROM audit_events"
    params: list[Any] = []

    if task_id:
        query += " WHERE task_id = ?"
        params.append(task_id)

    query += " ORDER BY sequence_number DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()

    events: list[dict[str, Any]] = []
    for row in rows:
        event_dict: dict[str, Any] = dict(row)
        metadata = event_dict.get("metadata")
        if isinstance(metadata, str) and metadata:
            try:
                event_dict["metadata"] = json.loads(metadata)
            except json.JSONDecodeError:
                pass
        events.append(event_dict)

    return AuditLogResponse(events=events, total=len(events))