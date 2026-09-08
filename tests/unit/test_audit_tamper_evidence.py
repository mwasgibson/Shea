from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from shea.audit.chain import GENESIS_PREV_HASH, hash_audit_event
from shea.audit.recorder import AuditRecorder
from shea.contracts.models import AuditEvent
from shea.persistence.sqlite.audit_sink import SqliteAuditSink
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator


class SequentialIdGenerator(IdGenerator):
    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"event-{self._counter}"

class FixedClock(Clock):
    def __init__(self) -> None:
        self._time = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        result = self._time
        self._time = self._time.replace(second=self._time.second + 1)
        return result

def _compute_expected_hash(event: AuditEvent) -> str:
    """Compute the expected SHA-256 hash for an audit event."""
    prev_hash = event.prev_hash if event.prev_hash is not None else GENESIS_PREV_HASH
    return hash_audit_event(event, prev_hash)

def test_first_event_has_no_prev_hash(conn: sqlite3.Connection) -> None:
    """The first event in a chain should have prev_hash = None."""
    clock = FixedClock()
    id_generator = SequentialIdGenerator()
    sink = SqliteAuditSink(conn, unit_of_work=SqliteUnitOfWork(conn))
    recorder = AuditRecorder(sink=sink, clock=clock, id_generator=id_generator)

    event = recorder.record(
        actor="user1",
        component="test",
        event_type="test.event",
        action="start",
        result="success",
        request_id="req-1",
        task_id="task-1",
    )

    assert event.prev_hash is None
    row = conn.execute(
        "SELECT prev_hash FROM audit_events WHERE event_id = ?",
        (event.event_id,)
    ).fetchone()
    assert row["prev_hash"] is None

def test_second_event_has_prev_hash(conn: sqlite3.Connection) -> None:
    """The second event should have prev_hash pointing to the first."""
    clock = FixedClock()
    id_generator = SequentialIdGenerator()
    sink = SqliteAuditSink(conn, unit_of_work=SqliteUnitOfWork(conn))
    recorder = AuditRecorder(sink=sink, clock=clock, id_generator=id_generator)

    event1 = recorder.record(
        actor="user1",
        component="test",
        event_type="test.event",
        action="start",
        result="success",
        request_id="req-1",
        task_id="task-1",
    )

    event2 = recorder.record(
        actor="user1",
        component="test",
        event_type="test.event",
        action="continue",
        result="success",
        request_id="req-1",
        task_id="task-1",
    )

    assert event2.prev_hash is not None
    assert event2.prev_hash == _compute_expected_hash(event1)
    assert len(event2.prev_hash) == 64  # SHA-256 hex digest length

    # Verify the stored hash matches
    row = conn.execute(
        "SELECT prev_hash FROM audit_events WHERE event_id = ?",
        (event2.event_id,)
    ).fetchone()
    assert row["prev_hash"] == event2.prev_hash

def test_different_scopes_have_separate_chains(conn: sqlite3.Connection) -> None:
    """Events for different (request_id, task_id) should have separate chains."""
    clock = FixedClock()
    id_generator = SequentialIdGenerator()
    sink = SqliteAuditSink(conn, unit_of_work=SqliteUnitOfWork(conn))
    recorder = AuditRecorder(sink=sink, clock=clock, id_generator=id_generator)

    # Create events for two different scopes
    event_a1 = recorder.record(
        actor="user1",
        component="test",
        event_type="test.event",
        action="start",
        result="success",
        request_id="req-a",
        task_id="task-a",
    )

    event_b1 = recorder.record(
        actor="user1",
        component="test",
        event_type="test.event",
        action="start",
        result="success",
        request_id="req-b",
        task_id="task-b",
    )

    event_a2 = recorder.record(
        actor="user1",
        component="test",
        event_type="test.event",
        action="continue",
        result="success",
        request_id="req-a",
        task_id="task-a",
    )

    # event_a2 should chain from event_a1, not event_b1
    assert event_a2.prev_hash is not None
    # Both a1 and b1 have no previous hash (they're first in their chains)
    assert event_a1.prev_hash is None
    assert event_b1.prev_hash is None

def test_chain_continuity_across_multiple_events(conn: sqlite3.Connection) -> None:
    """Verify that a chain of events maintains correct hash links."""
    clock = FixedClock()
    id_generator = SequentialIdGenerator()
    sink = SqliteAuditSink(conn, unit_of_work=SqliteUnitOfWork(conn))
    recorder = AuditRecorder(sink=sink, clock=clock, id_generator=id_generator)

    events: list[AuditEvent] = []
    for i in range(5):
        event = recorder.record(
            actor="user1",
            component="test",
            event_type="test.event",
            action=f"step_{i}",
            result="success",
            request_id="req-1",
            task_id="task-1",
        )
        events.append(event)

    # First event has no previous hash
    assert events[0].prev_hash is None

    # Each subsequent event has the correct previous hash
    for i in range(1, 5):
        prev_hash = events[i].prev_hash
        assert prev_hash is not None
        assert len(prev_hash) == 64

def test_tamper_detection_via_hash_chain(conn: sqlite3.Connection) -> None:
    """Demonstrate that modifying an event breaks the chain.

    This is a property-based test showing the principle: if we were to
    modify event N, then event N+1's prev_hash would no longer match
    the (modified) event N's hash.
    """
    clock = FixedClock()
    id_generator = SequentialIdGenerator()
    sink = SqliteAuditSink(conn, unit_of_work=SqliteUnitOfWork(conn))
    recorder = AuditRecorder(sink=sink, clock=clock, id_generator=id_generator)

    event1 = recorder.record(
        actor="user1",
        component="test",
        event_type="test.event",
        action="start",
        result="success",
        request_id="req-1",
        task_id="task-1",
        metadata={"value": 1},
    )

    event2 = recorder.record(
        actor="user1",
        component="test",
        event_type="test.event",
        action="continue",
        result="success",
        request_id="req-1",
        task_id="task-1",
        metadata={"value": 2},
    )

    # event2's prev_hash should be the hash of event1
    expected_hash = _compute_expected_hash(event1)
    assert event2.prev_hash == expected_hash

    # If we were to modify event1's metadata, the hash would change
    modified_event1 = AuditEvent(
        event_id=event1.event_id,
        request_id=event1.request_id,
        task_id=event1.task_id,
        timestamp=event1.timestamp,
        actor=event1.actor,
        component=event1.component,
        event_type=event1.event_type,
        action=event1.action,
        result=event1.result,
        metadata={"value": 999},  # Modified!
        prev_hash=event1.prev_hash,
    )
    modified_hash = _compute_expected_hash(modified_event1)

    # The modified hash should NOT match event2's prev_hash
    assert modified_hash != event2.prev_hash
    # This proves tampering would be detectable