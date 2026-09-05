from __future__ import annotations

import json
import sqlite3

from shea.contracts.models import AuditEvent

from .unit_of_work import SqliteUnitOfWork


class SqliteAuditSink:
    """Concrete adapter for the AuditSink port.

    Deliberately exposes only `record` (insert) — no update/delete method
    exists on this class, so accidental mutation of audit history is a
    type error, not just a code-review concern.
    """

    def __init__(self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def record(self, event: AuditEvent) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO audit_events
                    (event_id, request_id, task_id, timestamp, actor,
                     component, event_type, action, result, metadata)
                VALUES
                    (:event_id, :request_id, :task_id, :timestamp, :actor,
                     :component, :event_type, :action, :result, :metadata)
                """,
                {
                    "event_id": event.event_id,
                    "request_id": event.request_id,
                    "task_id": event.task_id,
                    "timestamp": event.timestamp.isoformat(),
                    "actor": event.actor,
                    "component": event.component,
                    "event_type": event.event_type,
                    "action": event.action,
                    "result": event.result,
                    "metadata": json.dumps(event.metadata),
                },
            )