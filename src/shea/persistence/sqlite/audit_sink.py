from __future__ import annotations

import json
import sqlite3

from shea.audit.chain import GENESIS_PREV_HASH, hash_audit_event
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

    def record(self, event: AuditEvent) -> AuditEvent:
        with self._uow:
            tip = self._conn.execute(
                "SELECT sequence_number, event_hash FROM audit_events "
                "WHERE request_id IS ? AND task_id IS ? "
                "ORDER BY sequence_number DESC LIMIT 1",
                (event.request_id, event.task_id),
            ).fetchone()
            next_sequence_number = self._conn.execute(
                "SELECT COALESCE(MAX(sequence_number), 0) + 1 "
                "FROM audit_events"
            ).fetchone()[0]
            if tip is None:
                sequence_number = event.sequence_number or next_sequence_number
                prev_hash = event.prev_hash
            else:
                sequence_number = event.sequence_number or next_sequence_number
                prev_hash = event.prev_hash or tip["event_hash"]

            calc_prev_hash = prev_hash if prev_hash is not None else GENESIS_PREV_HASH
            event_hash = event.event_hash or hash_audit_event(event, calc_prev_hash)
            
            event.sequence_number = sequence_number
            event.prev_hash = prev_hash
            event.event_hash = event_hash
            
            self._conn.execute(
                """
                INSERT INTO audit_events
                    (event_id, request_id, task_id, timestamp, actor,
                     component, event_type, action, result, metadata,
                     sequence_number, prev_hash, event_hash)
                VALUES
                    (:event_id, :request_id, :task_id, :timestamp, :actor,
                     :component, :event_type, :action, :result, :metadata,
                     :sequence_number, :prev_hash, :event_hash)
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
                    "sequence_number": sequence_number,
                    "prev_hash": prev_hash,
                    "event_hash": event_hash,
                },
            )
            
            return event