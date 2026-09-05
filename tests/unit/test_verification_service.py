from __future__ import annotations

import sqlite3

import pytest

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import TaskState
from shea.contracts.models import Task, ToolExecutionRecord
from shea.core.orchestrator import Orchestrator
from shea.persistence.sqlite.tool_execution_repository import SqliteToolExecutionRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.persistence.sqlite.verification_repository import SqliteVerificationRepository
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.verification.service import (
    MissingExecutionRecordError,
    TaskNotVerifyingError,
    VerificationService,
)
from shea.verification.verifier import VerificationOutcome, VerifierRegistry


def test_verified_execution_advances_task_to_completed(
    verification_service: VerificationService, verifying_task: Task
) -> None:
    result = verification_service.verify(verifying_task)

    assert result.verification.verified is True
    assert result.task.state == TaskState.COMPLETED


def test_custom_verifier_can_override_execution_report(
    verifier_registry: VerifierRegistry,
    orchestrator: Orchestrator,
    tool_execution_repository: SqliteToolExecutionRepository,
    verification_repository: SqliteVerificationRepository,
    unit_of_work: SqliteUnitOfWork,
    audit_recorder: AuditRecorder,
    clock: Clock,
    id_generator: IdGenerator,
    verifying_task: Task,
) -> None:
    """EXECUTION SUCCESS != VERIFIED SUCCESS (Appendix B): a tool
    reporting success does not force verification to agree. A
    tool-specific Verifier can independently decide the claimed outcome
    did not actually occur, and the task ends up FAILED, not COMPLETED,
    even though execution itself reported success.
    """

    def always_unverified(task: Task, record: ToolExecutionRecord) -> VerificationOutcome:
        return VerificationOutcome(
            verified=False, method="independent_check", explanation="disagreed with tool report"
        )

    verifier_registry.register("echo", always_unverified)

    service = VerificationService(
        verifier_registry=verifier_registry,
        orchestrator=orchestrator,
        tool_execution_repository=tool_execution_repository,
        verification_repository=verification_repository,
        audit=audit_recorder,
        clock=clock,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
    )

    result = service.verify(verifying_task)

    assert result.verification.verified is False
    assert result.verification.method == "independent_check"
    assert result.task.state == TaskState.FAILED


def test_verification_on_non_verifying_task_raises(
    verification_service: VerificationService, ready_task: Task
) -> None:
    with pytest.raises(TaskNotVerifyingError):
        verification_service.verify(ready_task)


def test_verification_without_execution_record_raises(
    verifier_registry: VerifierRegistry,
    orchestrator: Orchestrator,
    tool_execution_repository: SqliteToolExecutionRepository,
    verification_repository: SqliteVerificationRepository,
    unit_of_work: SqliteUnitOfWork,
    audit_recorder: AuditRecorder,
    clock: Clock,
    id_generator: IdGenerator,
) -> None:
    task = orchestrator.create_task(session_id="session-1", request_id="req-1")
    orchestrator.advance(task.id, "start_planning")
    orchestrator.advance(task.id, "plan_ready")
    orchestrator.advance(task.id, "authorize_and_run")
    # Deliberately skip ExecutionService, so no ToolExecutionRecord exists.
    verifying = orchestrator.advance(task.id, "execution_complete")

    service = VerificationService(
        verifier_registry=verifier_registry,
        orchestrator=orchestrator,
        tool_execution_repository=tool_execution_repository,
        verification_repository=verification_repository,
        audit=audit_recorder,
        clock=clock,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
    )

    with pytest.raises(MissingExecutionRecordError):
        service.verify(verifying)


def test_verified_success_is_audited(
    verification_service: VerificationService, verifying_task: Task, conn: sqlite3.Connection
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
    verification_repository: SqliteVerificationRepository,
) -> None:
    verification_service.verify(verifying_task)

    records = verification_repository.list_by_task(verifying_task.id)
    assert len(records) == 1
    assert records[0].verified is True