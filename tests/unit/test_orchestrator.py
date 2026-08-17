from __future__ import annotations

import sqlite3

import pytest

from shea.contracts.enums import TaskState
from shea.core.orchestrator import Orchestrator, TaskNotFoundError
from shea.state_machine.transitions import IllegalTransitionError


def test_create_task_starts_in_created_state(orchestrator: Orchestrator) -> None:
    task = orchestrator.create_task(session_id="session-1", request_id="req-1")

    assert task.state == TaskState.CREATED
    assert task.session_id == "session-1"
    assert task.request_id == "req-1"


def test_create_task_is_persisted(orchestrator: Orchestrator) -> None:
    created = orchestrator.create_task(session_id="session-1", request_id="req-1")

    fetched = orchestrator.get_task(created.id)

    assert fetched.id == created.id
    assert fetched.state == TaskState.CREATED


def test_get_missing_task_raises(orchestrator: Orchestrator) -> None:
    with pytest.raises(TaskNotFoundError):
        orchestrator.get_task("does-not-exist")


def test_advance_happy_path_to_completed(orchestrator: Orchestrator) -> None:
    task = orchestrator.create_task(session_id="session-1", request_id="req-1")

    task = orchestrator.advance(task.id, "start_planning")
    assert task.state == TaskState.PLANNING

    task = orchestrator.advance(task.id, "plan_ready")
    assert task.state == TaskState.READY

    task = orchestrator.advance(task.id, "authorize_and_run")
    assert task.state == TaskState.RUNNING

    task = orchestrator.advance(task.id, "execution_complete")
    assert task.state == TaskState.VERIFYING

    task = orchestrator.advance(task.id, "verified")
    assert task.state == TaskState.COMPLETED


def test_illegal_transition_raises_and_leaves_state_unchanged(
    orchestrator: Orchestrator,
) -> None:
    task = orchestrator.create_task(session_id="session-1", request_id="req-1")

    with pytest.raises(IllegalTransitionError):
        orchestrator.advance(task.id, "authorize_and_run")  # can't skip planning

    unchanged = orchestrator.get_task(task.id)
    assert unchanged.state == TaskState.CREATED


def test_illegal_transition_is_still_audited(
    orchestrator: Orchestrator, conn: sqlite3.Connection
) -> None:
    task = orchestrator.create_task(session_id="session-1", request_id="req-1")

    with pytest.raises(IllegalTransitionError):
        orchestrator.advance(task.id, "authorize_and_run")

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (task.id, "task.transition.rejected"),
    ).fetchall()

    assert len(rows) == 1
    assert rows[0]["result"] == "illegal_transition"
    assert rows[0]["action"] == "authorize_and_run"


def test_successful_transition_is_audited(
    orchestrator: Orchestrator, conn: sqlite3.Connection
) -> None:
    task = orchestrator.create_task(session_id="session-1", request_id="req-1")
    orchestrator.advance(task.id, "start_planning")

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (task.id, "task.transition"),
    ).fetchall()

    assert len(rows) == 1
    assert rows[0]["result"] == "success"


def test_cancel_from_ready_state(orchestrator: Orchestrator) -> None:
    task = orchestrator.create_task(session_id="session-1", request_id="req-1")
    orchestrator.advance(task.id, "start_planning")
    orchestrator.advance(task.id, "plan_ready")

    task = orchestrator.advance(task.id, "cancel")

    assert task.state == TaskState.CANCELLED

    with pytest.raises(IllegalTransitionError):
        orchestrator.advance(task.id, "authorize_and_run")
