from __future__ import annotations

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import (
    RecoveryStrategy,
    TaskState,
)
from shea.contracts.models import (
    RecoveryAttempt,
    RecoveryDecision,
    RetryPolicy,
    Task,
)
from shea.core.orchestrator import Orchestrator
from shea.ports.id_generator import IdGenerator
from shea.ports.repositories import (
    RecoveryAttemptRepository,
    ToolExecutionRepository,
    VerificationRepository,
)
from shea.ports.unit_of_work import UnitOfWork

from .classifier import FailureClassifier
from .compensator import Compensator, default_compensator
from .planner import RecoveryPlanner
from .retry import RetryController


class TaskNotFailedError(Exception):
    def __init__(self, task_id: str, actual_state: TaskState) -> None:
        self.task_id = task_id
        self.actual_state = actual_state
        super().__init__(
            f"Task {task_id!r} is not FAILED (currently {actual_state.value!r}); "
            "recovery can only begin from FAILED."
        )


class TaskNotRecoveringError(Exception):
    def __init__(self, task_id: str, actual_state: TaskState) -> None:
        self.task_id = task_id
        self.actual_state = actual_state
        super().__init__(
            f"Task {task_id!r} is not RECOVERING (currently {actual_state.value!r}); "
            "recovery can only be resolved from RECOVERING."
        )


class TaskNotBlockedError(Exception):
    def __init__(self, task_id: str, actual_state: TaskState) -> None:
        self.task_id = task_id
        self.actual_state = actual_state
        super().__init__(
            f"Task {task_id!r} is not BLOCKED (currently {actual_state.value!r})."
        )


class MissingRecoveryAttemptError(Exception):
    """Raised if resolve_recovery is called on a task with no recorded
    attempt — structurally shouldn't happen since begin_recovery always
    persists one first, but checked defensively rather than assumed.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"Task {task_id!r} is RECOVERING but has no RecoveryAttempt on file.")


class RecoveryExhaustedError(Exception):
    """Raised when begin_recovery would exceed max_attempts. The task is
    deliberately left in FAILED — RecoveryService does not force it
    anywhere else, since giving up is a fact to report, not a transition
    to make on the task's behalf.
    """

    def __init__(self, task_id: str, attempts_made: int, max_attempts: int) -> None:
        self.task_id = task_id
        self.attempts_made = attempts_made
        self.max_attempts = max_attempts
        super().__init__(
            f"Task {task_id!r} has exhausted its recovery budget "
            f"({attempts_made}/{max_attempts} attempts already made)."
        )


class RecoveryService:
    """Technical doc Component: Recovery Manager ("Handles retries and
    compensation"), implementing research doc Section 15.1's Saga-Style
    Recovery loop:

        FAILED --retry--> RECOVERING --(compensate, verify)--> READY | FAILED

    plus resolution of BLOCKED tasks (Phase 3's UNKNOWN-outcome landing
    state), which otherwise has no way back out.

    Retries are bounded by `RetryController` (backed by `RetryPolicy.
    max_attempts`), counted from persisted RecoveryAttempt rows rather
    than an in-memory counter, so the limit survives process restarts
    (technical doc Section 14: task state is persistent, not RAM-only).
    `RetryController.delay_for()` also supplies the backoff delay for
    each attempt, which is persisted on the `RecoveryAttempt` itself
    rather than computed and discarded — Phase 8 found this class built,
    unit-tested, and never actually called from here; see the Phase 8
    review for the full story.
    """

    def __init__(
        self,
        *,
        orchestrator: Orchestrator,
        recovery_attempt_repository: RecoveryAttemptRepository,
        tool_execution_repository: ToolExecutionRepository,
        verification_repository: VerificationRepository,
        audit: AuditRecorder,
        id_generator: IdGenerator,
        unit_of_work: UnitOfWork,
        classifier: FailureClassifier | None = None,
        planner: RecoveryPlanner | None = None,
        retry_controller: RetryController | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._attempts = recovery_attempt_repository
        self._executions = tool_execution_repository
        self._verifications = verification_repository
        self._audit = audit
        self._ids = id_generator
        self._uow = unit_of_work
        self._classifier = classifier or FailureClassifier()
        self._planner = planner or RecoveryPlanner()
        self._retry = retry_controller or RetryController(RetryPolicy())

    def plan_recovery(self, task: Task) -> RecoveryDecision:
        if task.state is not TaskState.FAILED:
            raise TaskNotFailedError(task.id, task.state)

        execution = self._executions.get_latest_by_task(task.id)

        if execution is None:
            raise ValueError(
                f"Task {task.id!r} has no execution record."
            )

        attempts = self._attempts.list_by_task(task.id)
        verification = self._verifications.get_latest_by_task(task.id)

        classification = self._classifier.classify(execution)

        decision = self._planner.decide(
            execution,
            classification,
            attempts_made=len(attempts),
            verification=verification,
        )

        self._audit.record(
            actor="recovery_service",
            component="recovery.planner",
            event_type="recovery.decision",
            action="plan_recovery",
            result=decision.strategy.value,
            request_id=task.request_id,
            task_id=task.id,
            metadata={
                "strategy": decision.strategy.value,
                "reason": decision.reason,
                "failure_category": classification.category.value,
                "retryable": classification.retryable,
                "recoverable": classification.recoverable,
            },
        )

        return decision

    def begin_recovery(self, task: Task) -> Task:
        previous_attempts = self._attempts.list_by_task(task.id)
        attempt_number = len(previous_attempts) + 1

        # RetryController is the single source of truth for the attempt
        # budget now — not a locally duplicated max_attempts field that
        # could silently drift from RetryPolicy's own default.
        if not self._retry.can_retry(len(previous_attempts)):
            raise RecoveryExhaustedError(
                task.id,
                len(previous_attempts),
                self._retry.max_attempts,
            )

        decision = self.plan_recovery(task)

        if decision.strategy is RecoveryStrategy.SECURITY_HALT:
            return self._orchestrator.advance(task.id, "security_halt")

        if decision.strategy is RecoveryStrategy.ABORT:
            raise RecoveryExhaustedError(
                task.id,
                len(previous_attempts),
                self._retry.max_attempts,
            )

        delay_seconds = self._retry.delay_for(attempt_number)

        with self._uow:
            self._attempts.save(
                RecoveryAttempt(
                    id=self._ids.new_id(),
                    task_id=task.id,
                    attempt_number=attempt_number,
                    delay_seconds=delay_seconds,
                )
            )

            self._audit.record(
                actor="recovery_service",
                component="recovery.manager",
                event_type="recovery.attempt_started",
                action="begin_recovery",
                result="attempting",
                request_id=task.request_id,
                task_id=task.id,
                metadata={
                    "attempt_number": attempt_number,
                    "strategy": decision.strategy.value,
                    "delay_seconds": delay_seconds,
                },
            )

        return self._orchestrator.advance(task.id, "retry")

    def resolve_recovery(
        self,
        task: Task,
        compensator: Compensator = default_compensator,
    ) -> Task:
        if task.state is not TaskState.RECOVERING:
            raise TaskNotRecoveringError(task.id, task.state)

        attempt = self._attempts.get_latest_by_task(task.id)

        if attempt is None:
            raise MissingRecoveryAttemptError(task.id)

        outcome = compensator(task)

        attempt.resolved = True
        attempt.recovered = outcome.restored
        attempt.method = outcome.method
        attempt.explanation = outcome.explanation

        with self._uow:
            self._attempts.save(attempt)

            self._audit.record(
                actor="recovery_service",
                component="recovery.manager",
                event_type=(
                    "recovery.recovered"
                    if outcome.restored
                    else "recovery.failed"
                ),
                action="resolve_recovery",
                result=(
                    "recovered"
                    if outcome.restored
                    else "not_recovered"
                ),
                request_id=task.request_id,
                task_id=task.id,
                metadata={
                    "attempt_number": attempt.attempt_number,
                    "method": outcome.method,
                },
            )

        return self._orchestrator.advance(
            task.id,
            "recovered" if outcome.restored else "recovery_failed",
        )

    def resolve_blocked(self, task: Task, *, resume: bool) -> Task:
        """Resolve a BLOCKED task, regardless of why it was blocked (a
        planning `block` event or an UNKNOWN execution outcome both land
        here) — `resume=True` returns it to READY for re-authorization
        and re-execution; `resume=False` cancels it outright.
        """
        if task.state is not TaskState.BLOCKED:
            raise TaskNotBlockedError(task.id, task.state)

        event = "unblock" if resume else "cancel"

        self._audit.record(
            actor="recovery_service",
            component="recovery.manager",
            event_type="recovery.blocked_resolved",
            action="resolve_blocked",
            result="resumed" if resume else "cancelled",
            request_id=task.request_id,
            task_id=task.id,
            metadata={"resumed": resume},
        )

        return self._orchestrator.advance(task.id, event)