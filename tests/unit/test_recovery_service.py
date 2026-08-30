from __future__ import annotations

import sqlite3

import pytest

from shea.contracts.enums import TaskState
from shea.contracts.models import Task
from shea.core.orchestrator import Orchestrator
from shea.persistence.sqlite.recovery_attempt_repository import SqliteRecoveryAttemptRepository
from shea.recovery.compensator import CompensationOutcome
from shea.recovery.service import (
    RecoveryExhaustedError,
    RecoveryService,
    TaskNotBlockedError,
    TaskNotFailedError,
    TaskNotRecoveringError,
)


def test_begin_recovery_moves_failed_task_to_recovering(
    recovery_service: RecoveryService, failed_task: Task
) -> None:
    task = recovery_service.begin_recovery(failed_task)
    assert task.state == TaskState.RECOVERING


def test_begin_recovery_on_non_failed_task_raises(
    recovery_service: RecoveryService, ready_task: Task
) -> None:
    with pytest.raises(TaskNotFailedError):
        recovery_service.begin_recovery(ready_task)


def test_resolve_recovery_with_default_compensator_never_claims_success(
    recovery_service: RecoveryService, failed_task: Task
) -> None:
    """Constraint 5: "Rollback must never be claimed successful without
    verification." With no real compensator configured, the honest
    outcome is `recovered=False` — the default must never optimistically
    report success it didn't confirm.
    """
    recovering = recovery_service.begin_recovery(failed_task)

    task = recovery_service.resolve_recovery(recovering)

    assert task.state == TaskState.FAILED


def test_resolve_recovery_with_confirmed_compensator_returns_to_ready(
    recovery_service: RecoveryService, failed_task: Task
) -> None:
    def confirmed_compensator(task: Task) -> CompensationOutcome:
        return CompensationOutcome(
            restored=True, method="undo_write", explanation="confirmed via re-read"
        )

    recovering = recovery_service.begin_recovery(failed_task)

    task = recovery_service.resolve_recovery(recovering, compensator=confirmed_compensator)

    assert task.state == TaskState.READY


def test_resolve_recovery_on_non_recovering_task_raises(
    recovery_service: RecoveryService, failed_task: Task
) -> None:
    with pytest.raises(TaskNotRecoveringError):
        recovery_service.resolve_recovery(failed_task)


def test_recovery_attempts_are_bounded(
    recovery_service: RecoveryService, orchestrator: Orchestrator, failed_task: Task
) -> None:
    """Retries need strict limits (research doc Section 8.14) — this
    proves the limit is enforced from persisted attempt counts, not an
    in-memory counter that could reset.
    """
    task = failed_task
    for _ in range(3):  # default max_attempts
        recovering = recovery_service.begin_recovery(task)
        task = recovery_service.resolve_recovery(recovering)  # always fails -> FAILED
        assert task.state == TaskState.FAILED

    with pytest.raises(RecoveryExhaustedError) as exc_info:
        recovery_service.begin_recovery(task)

    assert exc_info.value.attempts_made == 3
    assert exc_info.value.max_attempts == 3
    # Exhaustion must not silently move the task anywhere.
    unchanged = orchestrator.get_task(task.id)
    assert unchanged.state == TaskState.FAILED


def test_resolve_blocked_with_resume_returns_to_ready(
    recovery_service: RecoveryService, orchestrator: Orchestrator, ready_task: Task
) -> None:
    blocked = orchestrator.advance(ready_task.id, "block")

    task = recovery_service.resolve_blocked(blocked, resume=True)

    assert task.state == TaskState.READY


def test_resolve_blocked_without_resume_cancels(
    recovery_service: RecoveryService, orchestrator: Orchestrator, ready_task: Task
) -> None:
    blocked = orchestrator.advance(ready_task.id, "block")

    task = recovery_service.resolve_blocked(blocked, resume=False)

    assert task.state == TaskState.CANCELLED


def test_resolve_blocked_on_non_blocked_task_raises(
    recovery_service: RecoveryService, ready_task: Task
) -> None:
    with pytest.raises(TaskNotBlockedError):
        recovery_service.resolve_blocked(ready_task, resume=True)


def test_unrecovered_task_is_audited(
    recovery_service: RecoveryService, failed_task: Task, conn: sqlite3.Connection
) -> None:
    recovering = recovery_service.begin_recovery(failed_task)
    recovery_service.resolve_recovery(recovering)

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (failed_task.id, "recovery.failed"),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "not_recovered"


def test_recovery_attempt_is_persisted_with_resolution(
    recovery_service: RecoveryService,
    failed_task: Task,
    recovery_attempt_repository: SqliteRecoveryAttemptRepository,
) -> None:
    recovering = recovery_service.begin_recovery(failed_task)
    recovery_service.resolve_recovery(recovering)

    attempts = recovery_attempt_repository.list_by_task(failed_task.id)
    assert len(attempts) == 1
    assert attempts[0].attempt_number == 1
    assert attempts[0].resolved is True
    assert attempts[0].recovered is False