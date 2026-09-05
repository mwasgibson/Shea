from __future__ import annotations

from dataclasses import dataclass

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import TaskState
from shea.contracts.models import Task, VerificationRecord
from shea.core.orchestrator import Orchestrator
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.repositories import ToolExecutionRepository, VerificationRepository
from shea.ports.unit_of_work import UnitOfWork

from .verifier import VerifierRegistry


class TaskNotVerifyingError(Exception):
    def __init__(self, task_id: str, actual_state: TaskState) -> None:
        self.task_id = task_id
        self.actual_state = actual_state
        super().__init__(
            f"Task {task_id!r} is not VERIFYING (currently {actual_state.value!r}); "
            "verification can only run after execution_complete."
        )


class MissingExecutionRecordError(Exception):
    """Raised if a task reached VERIFYING with no ToolExecutionRecord on
    file. Structurally shouldn't happen — only ExecutionService moves a
    task into VERIFYING, and it always persists a record first — but this
    is checked defensively rather than assumed, matching the same pattern
    ExecutionService uses for MissingDecisionError.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(
            f"Task {task_id!r} is VERIFYING but has no ToolExecutionRecord; "
            "cannot determine what to verify."
        )


@dataclass(frozen=True)
class VerificationResult:
    verification: VerificationRecord
    task: Task


class VerificationService:
    """Technical doc Component: Verification Engine ("Confirms expected
    outcomes"). This is the ONLY subsystem allowed to call
    `Orchestrator.advance(task_id, "verified" | "verification_failed")`.

    Deliberately does not compute verification itself — it looks up the
    tool-specific Verifier (or the documented fallback) and records
    exactly what that Verifier decided, so "verified" always traces back
    to a specific, inspectable method rather than being an opaque
    boolean.
    """

    def __init__(
        self,
        *,
        verifier_registry: VerifierRegistry,
        orchestrator: Orchestrator,
        tool_execution_repository: ToolExecutionRepository,
        verification_repository: VerificationRepository,
        audit: AuditRecorder,
        clock: Clock,
        id_generator: IdGenerator,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._verifiers = verifier_registry
        self._orchestrator = orchestrator
        self._tool_executions = tool_execution_repository
        self._verifications = verification_repository
        self._audit = audit
        self._clock = clock
        self._ids = id_generator
        self._uow = unit_of_work

    def verify(self, task: Task) -> VerificationResult:
        if task.state is not TaskState.VERIFYING:
            raise TaskNotVerifyingError(task.id, task.state)

        record = self._tool_executions.get_latest_by_task(task.id)
        if record is None:
            raise MissingExecutionRecordError(task.id)

        verifier = self._verifiers.get(record.tool)
        outcome = verifier(task, record)

        verification = VerificationRecord(
            id=self._ids.new_id(),
            task_id=task.id,
            verified=outcome.verified,
            method=outcome.method,
            explanation=outcome.explanation,
        )
        with self._uow:
            self._verifications.save(verification)

            self._audit.record(
                actor="verification_service",
                component="verification.engine",
                event_type=(
                    "verification.verified" if outcome.verified else "verification.failed"
                ),
                action="verify",
                result="verified" if outcome.verified else "not_verified",
                request_id=task.request_id,
                task_id=task.id,
                metadata={"method": outcome.method, "tool": record.tool},
            )

        event = "verified" if outcome.verified else "verification_failed"
        advanced_task = self._orchestrator.advance(task.id, event)

        return VerificationResult(verification=verification, task=advanced_task)