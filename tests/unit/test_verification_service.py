from __future__ import annotations

import sqlite3

import pytest

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import TaskState
from shea.contracts.models import Task, ToolExecutionRecord, ToolRequest, ToolResponse
from shea.core.orchestrator import Orchestrator
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.repositories import ToolExecutionRepository, VerificationRepository
from shea.tools.registry import ToolAlreadyRegisteredError, ToolDeclaration, ToolRegistry
from shea.verification.service import (
    MissingExecutionRecordError,
    TaskNotVerifyingError,
    VerificationService,
)
from shea.verification.verifier import VerificationOutcome, VerifierRegistry
from tests.unit.test_orchestrator import _RaisingAuditSink  # pyright: ignore[reportPrivateUsage]


def test_verify_on_non_verifying_task_raises(
    verification_service: VerificationService, ready_task: Task
) -> None:
    with pytest.raises(TaskNotVerifyingError):
        verification_service.verify(ready_task)


def test_verify_without_execution_record_raises(
    verification_service: VerificationService,
    verifying_task: Task,
    conn: sqlite3.Connection,
) -> None:
    # Remove execution records for this task from SQLite
    with conn:
        conn.execute(
            "DELETE FROM tool_executions WHERE task_id = ?", (verifying_task.id,)
        )

    with pytest.raises(MissingExecutionRecordError):
        verification_service.verify(verifying_task)


def test_verify_success_advances_task_to_completed(
    verification_service: VerificationService, verifying_task: Task
) -> None:
    result = verification_service.verify(verifying_task)

    assert result.task.state == TaskState.COMPLETED
    assert result.verification.verified is True


def test_verify_failure_advances_task_to_failed(
    verification_service: VerificationService,
    verifying_task: Task,
    verifier_registry: VerifierRegistry,
    tool_registry: ToolRegistry,
) -> None:
    """A tool reporting success does NOT force verification to agree --
    a registered Verifier can independently disagree.
    """

    def dummy_handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data={})

    def failing_verifier(
        task: Task, record: ToolExecutionRecord
    ) -> VerificationOutcome:
        return VerificationOutcome(
            verified=False,
            method="failing_verifier",
            explanation="always fails",
        )

    try:
        tool_registry.register(
            ToolDeclaration(name="echo", capabilities=frozenset()),
            dummy_handler,
        )
    except ToolAlreadyRegisteredError:
        pass

    verifier_registry.register("echo", failing_verifier)

    result = verification_service.verify(verifying_task)

    assert result.task.state == TaskState.FAILED
    assert result.verification.verified is False


def test_verification_is_audited(
    verification_service: VerificationService,
    verifying_task: Task,
    conn: sqlite3.Connection,
) -> None:
    verification_service.verify(verifying_task)

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (verifying_task.id, "verification.verified"),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "verified"


def test_verification_record_is_persisted(
    verification_service: VerificationService,
    verifying_task: Task,
    verification_repository: VerificationRepository,
) -> None:
    verification_service.verify(verifying_task)

    records = verification_repository.list_by_task(verifying_task.id)
    assert len(records) == 1
    assert records[0].verified is True


def test_custom_verifier_can_override_execution_report(
    verification_service: VerificationService,
    verifying_task: Task,
    verifier_registry: VerifierRegistry,
    tool_registry: ToolRegistry,
) -> None:
    """EXECUTION SUCCESS != VERIFIED SUCCESS (Appendix B). A tool
    reporting success does NOT force the task to COMPLETED. A registered
    Verifier can independently disagree, and the task ends up FAILED.
    """

    def dummy_handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data={})

    def always_fail_verifier(
        task: Task, record: ToolExecutionRecord
    ) -> VerificationOutcome:
        return VerificationOutcome(
            verified=False,
            method="always_fail",
            explanation="override test",
        )

    try:
        tool_registry.register(
            ToolDeclaration(name="echo", capabilities=frozenset()),
            dummy_handler,
        )
    except ToolAlreadyRegisteredError:
        pass

    verifier_registry.register("echo", always_fail_verifier)

    result = verification_service.verify(verifying_task)

    assert result.verification.verified is False
    assert result.task.state == TaskState.FAILED


def test_verified_success_is_audited(
    verification_service: VerificationService,
    verifying_task: Task,
    conn: sqlite3.Connection,
) -> None:
    verification_service.verify(verifying_task)

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (verifying_task.id, "verification.verified"),
    ).fetchall()
    assert len(rows) == 1


def test_verification_on_non_verifying_task_raises(
    verification_service: VerificationService, ready_task: Task
) -> None:
    with pytest.raises(TaskNotVerifyingError):
        verification_service.verify(ready_task)


def test_verification_without_execution_record_raises(
    verification_service: VerificationService, running_task: Task
) -> None:
    running_task.state = TaskState.VERIFYING
    with pytest.raises(MissingExecutionRecordError):
        verification_service.verify(running_task)


def test_verification_service_transaction_rolls_back_on_audit_failure(
    verifying_task: Task,
    verifier_registry: VerifierRegistry,
    tool_execution_repository: ToolExecutionRepository,
    verification_repository: VerificationRepository,
    unit_of_work: SqliteUnitOfWork,
    orchestrator: Orchestrator,
    clock: Clock,
    id_generator: IdGenerator,
) -> None:
    """Phase 8: VerificationService now wraps verification save, audit,
    and task advancement in one transaction. Proves that if the audit
    write fails mid-transaction, the verification record is rolled back too.
    """
    broken_audit = AuditRecorder(
        sink=_RaisingAuditSink(), clock=clock, id_generator=id_generator
    )
    broken_service = VerificationService(
        verifier_registry=verifier_registry,
        orchestrator=orchestrator,
        tool_execution_repository=tool_execution_repository,
        verification_repository=verification_repository,
        audit=broken_audit,
        clock=clock,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
    )

    with pytest.raises(RuntimeError, match="simulated audit sink failure"):
        broken_service.verify(verifying_task)

    # Verification record must have been rolled back
    records = verification_repository.list_by_task(verifying_task.id)
    assert len(records) == 0

    # Task state must also remain unchanged
    unchanged = orchestrator.get_task(verifying_task.id)
    assert unchanged.state == TaskState.VERIFYING