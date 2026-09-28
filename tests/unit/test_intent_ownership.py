from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from shea.contracts.models import Intent, Request
from shea.persistence.sqlite.intent_repository import SqliteIntentRepository
from shea.persistence.sqlite.migrator import MIGRATIONS_DIR, run_migrations
from shea.persistence.sqlite.request_repository import SqliteRequestRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _intent(request_id: str) -> Intent:
    return Intent(
        id="intent-1",
        request_id=request_id,
        type="query",
        goal="say hi",
        parameters={"a": 1},
        confidence=0.9,
        source="text",
        created_at=NOW,
    )


def test_intent_is_owned_by_request_without_any_task(
    conn: sqlite3.Connection, unit_of_work: SqliteUnitOfWork
) -> None:
    requests = SqliteRequestRepository(conn, unit_of_work=unit_of_work)
    intents = SqliteIntentRepository(conn, unit_of_work=unit_of_work)
    requests.save(
        Request(
            request_id="req-1",
            session_id="s",
            actor="user",
            input="hi",
            source="text",
            created_at=NOW,
        )
    )
    intents.save(_intent("req-1"))

    stored = intents.get_by_request("req-1")
    assert stored is not None
    assert stored.request_id == "req-1"
    assert stored.parameters == {"a": 1}
    assert intents.get_by_request("nope") is None
    # No task exists for this request, so the task-shaped lookup finds nothing.
    assert intents.get_by_task("any-task") is None


def test_get_by_task_resolves_through_task_request_id(
    conn: sqlite3.Connection, unit_of_work: SqliteUnitOfWork
) -> None:
    intents = SqliteIntentRepository(conn, unit_of_work=unit_of_work)
    conn.execute(
        "INSERT INTO tasks (id, session_id, request_id, state, created_at, updated_at) "
        "VALUES ('task-1', 's', 'req-1', 'READY', ?, ?)",
        (NOW.isoformat(), NOW.isoformat()),
    )
    conn.commit()
    intents.save(_intent("req-1"))

    stored = intents.get_by_task("task-1")
    assert stored is not None
    assert stored.id == "intent-1"


def test_migration_0013_repoints_existing_intents_at_their_task_request(
    tmp_path: Path,
) -> None:
    old_dir = tmp_path / "old_migrations"
    old_dir.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.stem < "0013":
            shutil.copy(path, old_dir / path.name)

    db = sqlite3.connect(tmp_path / "legacy.db")
    db.row_factory = sqlite3.Row
    run_migrations(db, old_dir)
    ts = NOW.isoformat()
    db.execute(
        "INSERT INTO tasks (id, session_id, request_id, state, created_at, updated_at) "
        "VALUES ('task-1', 's', 'req-legacy', 'COMPLETED', ?, ?)",
        (ts, ts),
    )
    db.execute(
        "INSERT INTO intents (id, task_id, type, goal, parameters, confidence, source, created_at) "
        "VALUES ('intent-legacy', 'task-1', 'task', 'do it', '{}', 1.0, 'text', ?)",
        (ts,),
    )
    db.commit()

    applied = run_migrations(db)  # full migration set: only 0013 is new

    assert applied == ["0013_intent_request_ownership"]
    row = db.execute("SELECT request_id FROM intents WHERE id = 'intent-legacy'").fetchone()
    assert row["request_id"] == "req-legacy"
    db.close()
