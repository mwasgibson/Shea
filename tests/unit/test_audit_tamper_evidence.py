from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from shea.audit.chain import GENESIS_PREV_HASH, hash_audit_event
from shea.audit.recorder import AuditRecorder
from shea.contracts.models import AuditEvent
from shea.persistence.sqlite.audit_chain import verify_audit_chain
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


def _make_recorder(conn: sqlite3.Connection) -> AuditRecorder:
    sink = SqliteAuditSink(conn, unit_of_work=SqliteUnitOfWork(conn))
    return AuditRecorder(sink=sink, clock=FixedClock(), id_generator=SequentialIdGenerator())


def test_first_event_ever_chains_from_the_genesis_marker(conn: sqlite3.Connection) -> None:
    """The very first audit event recorded, ever, chains from
    GENESIS_PREV_HASH — not None. Storing None here while having
    actually computed the hash using GENESIS_PREV_HASH was the bug that
    made every fresh database fail verify_audit_chain() immediately;
    this pins the fix.
    """
    recorder = _make_recorder(conn)

    event = recorder.record(
        actor="user1",
        component="test",
        event_type="test.event",
        action="start",
        result="success",
        request_id="req-1",
        task_id="task-1",
    )

    assert event.prev_hash == GENESIS_PREV_HASH
    row = conn.execute(
        "SELECT prev_hash, sequence_number FROM audit_events WHERE event_id = ?",
        (event.event_id,),
    ).fetchone()
    assert row["prev_hash"] == GENESIS_PREV_HASH
    assert row["sequence_number"] == 1

    result = verify_audit_chain(conn)
    assert result.valid is True
    assert result.events_checked == 1


def test_second_event_chains_from_the_first(conn: sqlite3.Connection) -> None:
    recorder = _make_recorder(conn)

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

    assert event2.prev_hash == event1.event_hash
    assert len(event2.prev_hash or "") == 64
    assert verify_audit_chain(conn).valid is True


def test_interleaved_tasks_share_one_global_chain(conn: sqlite3.Connection) -> None:
    """Phase 8 finding: SqliteAuditSink.record() used to look up its
    "previous event" scoped to (request_id, task_id), while
    verify_audit_chain() checks one global chain ordered by
    sequence_number — so the moment two tasks' events interleaved
    (the normal case for any system running more than one task), the
    chain would falsely report itself as broken. Every event here
    chains from the global tip, regardless of which task it belongs to.
    """
    recorder = _make_recorder(conn)

    event_a1 = recorder.record(
        actor="user1", component="test", event_type="e", action="start",
        result="success", request_id="req-a", task_id="task-a",
    )
    event_b1 = recorder.record(
        actor="user1", component="test", event_type="e", action="start",
        result="success", request_id="req-b", task_id="task-b",
    )
    event_a2 = recorder.record(
        actor="user1", component="test", event_type="e", action="continue",
        result="success", request_id="req-a", task_id="task-a",
    )

    # event_b1 chains from event_a1 (different task), not from genesis —
    # there is exactly one chain, not one per task.
    assert event_b1.prev_hash == event_a1.event_hash
    # event_a2 chains from event_b1 (the actual global predecessor by
    # sequence_number), not from event_a1 (its own task's last event).
    assert event_a2.prev_hash == event_b1.event_hash

    result = verify_audit_chain(conn)
    assert result.valid is True
    assert result.events_checked == 3


def test_chain_continuity_across_many_events(conn: sqlite3.Connection) -> None:
    recorder = _make_recorder(conn)

    for i in range(10):
        recorder.record(
            actor="user1",
            component="test",
            event_type="test.event",
            action=f"step_{i}",
            result="success",
            request_id="req-1",
            task_id="task-1",
        )

    result = verify_audit_chain(conn)
    assert result.valid is True
    assert result.events_checked == 10


def test_altering_a_row_directly_is_detected(conn: sqlite3.Connection) -> None:
    """The actual attack this feature exists to catch: someone with
    direct database access edits a row after the fact, bypassing
    SqliteAuditSink (which never exposes update/delete) entirely.
    """
    recorder = _make_recorder(conn)
    recorder.record(
        actor="user1", component="test", event_type="e", action="a1",
        result="success", request_id="req-1", task_id="task-1",
    )
    target = recorder.record(
        actor="user1", component="test", event_type="e", action="a2",
        result="success", request_id="req-1", task_id="task-1",
    )
    recorder.record(
        actor="user1", component="test", event_type="e", action="a3",
        result="success", request_id="req-1", task_id="task-1",
    )
    assert verify_audit_chain(conn).valid is True

    conn.execute(
        "UPDATE audit_events SET result = 'tampered' WHERE event_id = ?",
        (target.event_id,),
    )
    conn.commit()

    result = verify_audit_chain(conn)
    assert result.valid is False
    kinds = {b.kind for b in result.breaks}
    # This tamper only changed `result`, leaving the stored event_hash
    # column untouched — so the row is internally inconsistent
    # (content_altered), but the *next* row's prev_hash still matches
    # that unchanged stored event_hash, so the link itself isn't broken.
    # A tamperer sophisticated enough to also recompute and patch the
    # target row's own event_hash to match its new content would pass
    # its own content_altered check — but would then break the link to
    # whatever comes after it, since that row's prev_hash still points
    # to the original hash. See the test below for that case.
    assert kinds == {"content_altered"}


def test_a_sophisticated_tamperer_who_fixes_the_altered_rows_own_hash_still_breaks_the_link(
    conn: sqlite3.Connection,
) -> None:
    """The harder case: an attacker who recomputes and patches the
    tampered row's own event_hash to match its new content defeats
    content_altered for that row — but has no way to also patch every
    later row's prev_hash without redoing the whole chain from that
    point forward, so the very next row's link breaks instead.
    """
    recorder = _make_recorder(conn)
    recorder.record(
        actor="user1", component="test", event_type="e", action="a1",
        result="success", request_id="req-1", task_id="task-1",
    )
    target = recorder.record(
        actor="user1", component="test", event_type="e", action="a2",
        result="success", request_id="req-1", task_id="task-1",
    )
    recorder.record(
        actor="user1", component="test", event_type="e", action="a3",
        result="success", request_id="req-1", task_id="task-1",
    )

    row = conn.execute(
        "SELECT prev_hash FROM audit_events WHERE event_id = ?", (target.event_id,)
    ).fetchone()
    tampered = AuditEvent(
        event_id=target.event_id,
        request_id=target.request_id,
        task_id=target.task_id,
        timestamp=target.timestamp,
        actor=target.actor,
        component=target.component,
        event_type=target.event_type,
        action=target.action,
        result="tampered",
        metadata=target.metadata,
    )
    recomputed_hash = hash_audit_event(tampered, row["prev_hash"])
    conn.execute(
        "UPDATE audit_events SET result = 'tampered', event_hash = ? WHERE event_id = ?",
        (recomputed_hash, target.event_id),
    )
    conn.commit()

    result = verify_audit_chain(conn)
    assert result.valid is False
    kinds = {b.kind for b in result.breaks}
    assert kinds == {"link_broken"}


def test_deleting_a_middle_row_is_detected(conn: sqlite3.Connection) -> None:
    recorder = _make_recorder(conn)
    recorder.record(
        actor="user1", component="test", event_type="e", action="a1",
        result="success", request_id="req-1", task_id="task-1",
    )
    victim = recorder.record(
        actor="user1", component="test", event_type="e", action="a2",
        result="success", request_id="req-1", task_id="task-1",
    )
    recorder.record(
        actor="user1", component="test", event_type="e", action="a3",
        result="success", request_id="req-1", task_id="task-1",
    )

    conn.execute("DELETE FROM audit_events WHERE event_id = ?", (victim.event_id,))
    conn.commit()

    result = verify_audit_chain(conn)
    assert result.valid is False
    kinds = {b.kind for b in result.breaks}
    assert "sequence_gap" in kinds
    assert "link_broken" in kinds


def test_deleting_only_the_most_recent_event_is_not_detectable(
    conn: sqlite3.Connection,
) -> None:
    """States the structural limitation plainly, pinned as a test rather
    than left only as a docstring claim: truncating just the chain's tail
    (and nothing else) leaves a chain that still verifies cleanly, because
    there is nothing recorded after the truncation point to notice the
    gap. This is not a bug to fix here — it is why `hash_audit_event`'s
    docstring says a hash chain alone cannot defend against tail
    truncation without an external anchor.
    """
    recorder = _make_recorder(conn)
    recorder.record(
        actor="user1", component="test", event_type="e", action="a1",
        result="success", request_id="req-1", task_id="task-1",
    )
    most_recent = recorder.record(
        actor="user1", component="test", event_type="e", action="a2",
        result="success", request_id="req-1", task_id="task-1",
    )

    conn.execute("DELETE FROM audit_events WHERE event_id = ?", (most_recent.event_id,))
    conn.commit()

    result = verify_audit_chain(conn)
    assert result.valid is True
    assert result.events_checked == 1


def test_hash_audit_event_is_deterministic_given_the_same_inputs(
    conn: sqlite3.Connection,
) -> None:
    """The pure hashing function itself: same event content + same
    prev_hash always produces the same hash, independent of any
    database round-trip.
    """
    event = AuditEvent(
        event_id="e1",
        request_id="req-1",
        task_id="task-1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        actor="user1",
        component="test",
        event_type="test.event",
        action="start",
        result="success",
        metadata={"key": "value"},
    )
    hash1 = hash_audit_event(event, GENESIS_PREV_HASH)
    hash2 = hash_audit_event(event, GENESIS_PREV_HASH)
    assert hash1 == hash2
    assert len(hash1) == 64

    different_prev = hash_audit_event(event, "1" * 64)
    assert different_prev != hash1