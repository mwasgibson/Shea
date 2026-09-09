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
            # Deliberately a single global chain ordered by
            # sequence_number, not scoped to this event's (request_id,
            # task_id) — verify_audit_chain() walks the whole table as
            # one chain, and a per-scope "previous event" lookup here
            # would silently disagree with that the moment two tasks'
            # events interleave, which is the normal case in any running
            # system. Also never honors chain fields already set on the
            # incoming `event` — a caller (or anything reusing an old
            # AuditEvent object) supplying its own prev_hash/sequence_
            # number/event_hash would be trusted blindly, defeating the
            # whole point of a tamper-evident chain. This method is the
            # only place these fields are allowed to come from.
            tip = self._conn.execute(
                "SELECT sequence_number, event_hash FROM audit_events "
                "ORDER BY sequence_number DESC LIMIT 1"
            ).fetchone()

            if tip is None:
                sequence_number = 1
                prev_hash = GENESIS_PREV_HASH
            else:
                sequence_number = tip["sequence_number"] + 1
                prev_hash = tip["event_hash"]

            event_hash = hash_audit_event(event, prev_hash)

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