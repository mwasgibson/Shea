from __future__ import annotations

from shea.app.recovery import ReconciliationResult
from shea.app.supervisor import ExecutionSupervisor
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
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.repositories import (
    AuthorizationRepository,
    DecisionRepository,
    RecoveryAttemptRepository,
    ToolExecutionRepository,
    VerificationRepository,
)
from shea.ports.unit_of_work import UnitOfWork

from .authority import RecoveryAuthority
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
        decision_repository: DecisionRepository | None = None,
        authorization_repository: AuthorizationRepository | None = None,
        clock: Clock | None = None,
        recovery_attempt_repository: RecoveryAttemptRepository,
        tool_execution_repository: ToolExecutionRepository,
        verification_repository: VerificationRepository,
        audit: AuditRecorder,
        id_generator: IdGenerator,
        unit_of_work: UnitOfWork,
        classifier: FailureClassifier | None = None,
        planner: RecoveryPlanner | None = None,
        retry_controller: RetryController | None = None,
        execution_supervisor: ExecutionSupervisor | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._decisions = decision_repository
        self._authorizations = authorization_repository
        self._clock = clock
        self._attempts = recovery_attempt_repository
        self._executions = tool_execution_repository
        self._verifications = verification_repository
        self._audit = audit
        self._ids = id_generator
        self._uow = unit_of_work
        self._classifier = classifier or FailureClassifier()
        self._planner = planner or RecoveryPlanner()
        self._retry = retry_controller or RetryController(RetryPolicy())
        self._execution_supervisor = execution_supervisor

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

    def _derive_authority(self, task: Task) -> RecoveryAuthority:
        from shea.recovery.authority import RecoveryAuthority, RecoveryAuthorityError

        if self._decisions is None or self._authorizations is None or self._clock is None:
            raise RecoveryAuthorityError(
                task.id, "recovery authority dependencies not wired"
            )
        decision = self._decisions.get_by_task(task.id)
        if decision is None:
            raise RecoveryAuthorityError(task.id, "no decision on file")
        auths = self._authorizations.list_by_task(task.id)
        if not auths:
            raise RecoveryAuthorityError(task.id, "no authorization on file")
        authorization = auths[-1]
        return RecoveryAuthority.from_original(
            decision=decision,
            authorization=authorization,
            max_attempts=self._retry.max_attempts,
            now=self._clock.now(),
        )

    def begin_recovery(self, task: Task) -> Task:
        self.reconcile_app_plane()
        task = self._orchestrator.get_task(task.id)

        if task.state is not TaskState.FAILED:
            raise TaskNotFailedError(task.id, task.state)    
            
        previous_attempts = self._attempts.list_by_task(task.id)
        attempt_number = len(previous_attempts) + 1
        authority = self._derive_authority(task)
        authority.assert_can(
            operation="retry",
            now=self._clock.now() if self._clock else task.updated_at,
            attempts_made=len(previous_attempts),
        )

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
                        "recovery_authority": authority.to_audit_dict(),
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
        
        authority = self._derive_authority(task)
        authority.assert_can(
            operation="compensate",
            now=self._clock.now() if self._clock else task.updated_at,
            attempts_made=max(0, attempt.attempt_number - 1),
        )

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

            advanced_task = self._orchestrator.advance(
                task.id,
                "recovered" if outcome.restored else "recovery_failed",
            )

        return advanced_task


    def stabilize(self, task: Task) -> Task:
        if task.state is not TaskState.STABILIZING:
            raise ValueError(f"Task is not stabilizing: {task.state}")
            
        # Here we could check metrics or delay, for now we immediately advance it
        with self._uow:
            self._audit.record(
                actor="recovery_service",
                component="recovery.stabilizer",
                event_type="recovery.stabilized",
                action="stabilize_task",
                result="ready",
                request_id=task.request_id,
                task_id=task.id,
            )
            advanced = self._orchestrator.advance(task.id, "stabilized")
            
        return advanced

    def resolve_blocked(self, task: Task, *, resume: bool) -> Task:
        """Resolve a BLOCKED task, regardless of why it was blocked (a
        planning `block` event or an UNKNOWN execution outcome both land
        here) — `resume=True` returns it to READY for re-authorization
        and re-execution; `resume=False` cancels it outright.
        """
        if task.state is not TaskState.BLOCKED:
            raise TaskNotBlockedError(task.id, task.state)

        event = "unblock" if resume else "cancel"
        
        authority = self._derive_authority(task)
        authority.assert_can(
            operation="resolve_blocked",
            now=self._clock.now() if self._clock else task.updated_at,
            attempts_made=0,
        )

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
    
    def reconcile_app_plane(self) -> list[ReconciliationResult]:
        """Reconcile stuck app-plane receipts (no adapter re-entry)."""
        if self._execution_supervisor is None:
            return []
        results = self._execution_supervisor.reconcile_stuck()
        with self._uow:
            for item in results:
                if item.detail == "nothing_to_reconcile":
                    continue
                self._audit.record(
                    actor="recovery_service",
                    component="recovery.app_plane",
                    event_type="recovery.app_receipt_reconciled",
                    action="reconcile",
                    result=item.outcome.value.lower(),
                    task_id=None,
                    metadata={
                        "receipt_id": item.receipt.id,
                        "detail": item.detail,
                        "fence_token": (
                            item.incident.fence_token if item.incident else None
                        ),
                    },
                )
        return list(results)
    def reconcile_stranded_tasks(self) -> list[Task]:
        """Sweep the database for tasks that were in-flight during an ungraceful shutdown
        and safely force them into terminal or stable states.
        """
        reconciled_tasks: list[Task] = []
        # First, ensure app-plane execution receipts are reconciled
        self.reconcile_app_plane()

        for task in self._orchestrator.list_transient_tasks():
            original_state = task.state
            if task.state in (TaskState.CREATED, TaskState.PLANNING, TaskState.READY):
                task = self._orchestrator.advance(task.id, "cancel")
            elif task.state == TaskState.RUNNING:
                task = self._orchestrator.advance(task.id, "execution_unknown")
            elif task.state == TaskState.VERIFYING:
                task = self._orchestrator.advance(task.id, "verification_failed")
            elif task.state == TaskState.RECOVERING:
                task = self._orchestrator.advance(task.id, "recovery_failed")
            else:
                continue

            self._audit.record(
                actor="system",
                component="recovery.reconciliation",
                event_type="recovery.task_reconciled",
                action="reconcile_stranded_tasks",
                result="reconciled",
                task_id=task.id,
                request_id=task.request_id,
                metadata={"original_state": original_state.value, "new_state": task.state.value}
            )
            reconciled_tasks.append(task)

        return reconciled_tasks