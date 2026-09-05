from __future__ import annotations

import sqlite3

from shea.audit.recorder import AuditRecorder
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.security.secrets import SecretRedactor


def test_metadata_is_redacted_when_redactor_is_configured(
    conn: sqlite3.Connection, clock: Clock, id_generator: IdGenerator
) -> None:
    from shea.persistence.sqlite.audit_sink import SqliteAuditSink
    from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork

    sink = SqliteAuditSink(conn, unit_of_work=SqliteUnitOfWork(conn))
    recorder = AuditRecorder(
        sink=sink, clock=clock, id_generator=id_generator, redactor=SecretRedactor()
    )

    recorder.record(
        actor="test",
        component="test.component",
        event_type="test.event",
        action="do",
        result="success",
        metadata={"note": "using key AKIAABCDEFGHIJKLMNOP for this call"},
    )

    row = conn.execute(
        "SELECT metadata FROM audit_events WHERE event_type = 'test.event'"
    ).fetchone()
    assert "AKIAABCDEFGHIJKLMNOP" not in row["metadata"]


def test_metadata_is_unchanged_without_a_redactor(
    conn: sqlite3.Connection, clock: Clock, id_generator: IdGenerator
) -> None:
    from shea.persistence.sqlite.audit_sink import SqliteAuditSink
    from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork

    sink = SqliteAuditSink(conn, unit_of_work=SqliteUnitOfWork(conn))
    recorder = AuditRecorder(sink=sink, clock=clock, id_generator=id_generator)

    recorder.record(
        actor="test",
        component="test.component",
        event_type="test.event",
        action="do",
        result="success",
        metadata={"note": "using key AKIAABCDEFGHIJKLMNOP for this call"},
    )

    row = conn.execute(
        "SELECT metadata FROM audit_events WHERE event_type = 'test.event'"
    ).fetchone()
    assert "AKIAABCDEFGHIJKLMNOP" in row["metadata"]