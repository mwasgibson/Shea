from __future__ import annotations

import sqlite3

import pytest

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import TaskState
from shea.contracts.models import Task
from shea.core.orchestrator import Orchestrator
from shea.persistence.sqlite.recovery_attempt_repository import SqliteRecoveryAttemptRepository
from shea.persistence.sqlite.tool_execution_repository import SqliteToolExecutionRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.persistence.sqlite.verification_repository import SqliteVerificationRepository
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.recovery.retry import RetryController, RetryPolicy
from shea.recovery.service import (
    RecoveryExhaustedError,
    RecoveryService,
    TaskNotFailedError,
    TaskNotRecoveringError,
)
from tests.unit.test_orchestrator import _RaisingAuditSink  # pyright: ignore[reportPrivateUsage]


def test_begin_recovery_on_non_failed_task_raises(
    recovery_service: RecoveryService, ready_task: Task
) -> None:
    reconciled = False

    def reconcile() -> list[object]:
        nonlocal reconciled
        reconciled = True
        return []

    recovery_service.reconcile_app_plane = reconcile  # type: ignore[method-assign]

    with pytest.raises(TaskNotFailedError):
        recovery_service.begin_recovery(ready_task)

    assert reconciled is True


def test_begin_recovery_persists_recovery_attempt(
    recovery_service: RecoveryService,
    recovery_attempt_repository: SqliteRecoveryAttemptRepository,
    failed_task: Task,
) -> None:
    recovery_service.begin_recovery(failed_task)

    attempts = recovery_attempt_repository.list_by_task(failed_task.id)
    assert len(attempts) == 1
    assert attempts[0].task_id == failed_task.id
    assert attempts[0].attempt_number == 1


def test_begin_recovery_advances_task_to_recovering(
    recovery_service: RecoveryService, failed_task: Task
) -> None:
    result = recovery_service.begin_recovery(failed_task)

    assert result.state == TaskState.RECOVERING


def test_begin_recovery_is_audited(
    recovery_service: RecoveryService, failed_task: Task, conn: sqlite3.Connection
) -> None:
    recovery_service.begin_recovery(failed_task)

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (failed_task.id, "recovery.attempt_started"),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "attempting"


def test_recovery_exhausted_raises(
    recovery_service: RecoveryService, failed_task: Task
) -> None:
    current_task = failed_task
    for _ in range(3):
        recovering = recovery_service.begin_recovery(current_task)
        current_task = recovery_service.resolve_recovery(recovering)

    with pytest.raises(RecoveryExhaustedError) as exc_info:
        recovery_service.begin_recovery(current_task)

    assert exc_info.value.attempts_made == 3


def test_recovery_exhausted_leaves_task_in_failed(
    recovery_service: RecoveryService, failed_task: Task, orchestrator: Orchestrator
) -> None:
    # Exhaust the retry budget
    current_task = failed_task
    for _ in range(3):
        recovering = recovery_service.begin_recovery(current_task)
        current_task = recovery_service.resolve_recovery(recovering)

    with pytest.raises(RecoveryExhaustedError):
        recovery_service.begin_recovery(current_task)

    unchanged = orchestrator.get_task(failed_task.id)
    assert unchanged.state == TaskState.FAILED


def test_resolve_recovery_on_non_recovering_task_raises(
    recovery_service: RecoveryService, failed_task: Task
) -> None:
    with pytest.raises(TaskNotRecoveringError):
        recovery_service.resolve_recovery(failed_task)


def test_resolve_recovery_updates_attempt_and_advances_task(
    recovery_service: RecoveryService,
    recovery_attempt_repository: SqliteRecoveryAttemptRepository,
    failed_task: Task,
) -> None:
    recovering_task = recovery_service.begin_recovery(failed_task)
    result = recovery_service.resolve_recovery(recovering_task)

    attempts = recovery_attempt_repository.list_by_task(failed_task.id)
    assert len(attempts) == 1
    assert attempts[0].resolved is True
    assert attempts[0].recovered is False

    assert result.state == TaskState.FAILED


def test_resolve_recovery_is_audited(
    recovery_service: RecoveryService, failed_task: Task, conn: sqlite3.Connection
) -> None:
    recovering_task = recovery_service.begin_recovery(failed_task)
    recovery_service.resolve_recovery(recovering_task)

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (failed_task.id, "recovery.failed"),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "not_recovered"


def test_begin_recovery_persists_retry_controllers_delay(
    recovery_service: RecoveryService,
    recovery_attempt_repository: SqliteRecoveryAttemptRepository,
    failed_task: Task,
) -> None:
    """Phase 8: RecoveryService now actually calls RetryController.delay_for()
    and persists the returned delay on the RecoveryAttempt. Proves the
    wiring gap found in Phase 8 is closed: the delay is real, not a
    hardcoded zero.
    """
    recovery_service.begin_recovery(failed_task)

    attempts = recovery_attempt_repository.list_by_task(failed_task.id)
    assert len(attempts) == 1
    # Default RetryPolicy uses exponential backoff: 2^0 = 1 second for first attempt
    assert attempts[0].delay_seconds == pytest.approx(1.0, abs=0.5)


def test_begin_recovery_honors_custom_retry_controllers_max_attempts(
    orchestrator: Orchestrator,
    recovery_attempt_repository: SqliteRecoveryAttemptRepository,
    tool_execution_repository: SqliteToolExecutionRepository,
    verification_repository: SqliteVerificationRepository,
    audit_recorder: AuditRecorder,
    id_generator: IdGenerator,
    unit_of_work: SqliteUnitOfWork,
    failed_task: Task,
) -> None:
    """Phase 8: RecoveryService now uses RetryController.can_retry() as the
    single source of truth for the attempt budget. Proves the wiring gap
    is closed: max_attempts comes from the controller, not a hardcoded value.
    """
    custom_retry = RetryController(RetryPolicy(max_attempts=1))
    custom_service = RecoveryService(
        orchestrator=orchestrator,
        recovery_attempt_repository=recovery_attempt_repository,
        tool_execution_repository=tool_execution_repository,
        verification_repository=verification_repository,
        audit=audit_recorder,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
        retry_controller=custom_retry,
    )

    custom_service.begin_recovery(failed_task)

    with pytest.raises(RecoveryExhaustedError) as exc_info:
        custom_service.begin_recovery(failed_task)

    assert exc_info.value.max_attempts == 1


def test_recovery_service_transaction_rolls_back_on_audit_failure(
    recovery_attempt_repository: SqliteRecoveryAttemptRepository,
    tool_execution_repository: SqliteToolExecutionRepository,
    verification_repository: SqliteVerificationRepository,
    failed_task: Task,
    unit_of_work: SqliteUnitOfWork,
    orchestrator: Orchestrator,
    clock: Clock,
    id_generator: IdGenerator,
) -> None:
    """Phase 8: RecoveryService now wraps recovery_attempt save, audit,
    and task advancement in one transaction. Proves that if the audit
    write fails mid-transaction, the attempt is rolled back too.
    """
    broken_audit = AuditRecorder(
        sink=_RaisingAuditSink(), clock=clock, id_generator=id_generator
    )
    broken_service = RecoveryService(
        orchestrator=orchestrator,
        recovery_attempt_repository=recovery_attempt_repository,
        tool_execution_repository=tool_execution_repository,
        verification_repository=verification_repository,
        audit=broken_audit,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
    )

    with pytest.raises(RuntimeError, match="simulated audit sink failure"):
        broken_service.begin_recovery(failed_task)

    # Recovery attempt must have been rolled back
    attempts = recovery_attempt_repository.list_by_task(failed_task.id)
    assert len(attempts) == 0

    # Task state must also remain unchanged
    unchanged = orchestrator.get_task(failed_task.id)
    assert unchanged.state == TaskState.FAILED