from __future__ import annotations

from dataclasses import dataclass

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import ExecutionOutcome, TaskState
from shea.contracts.models import Task, ToolExecutionRecord, ToolRequest, ToolResponse
from shea.core.orchestrator import Orchestrator
from shea.ports.id_generator import IdGenerator
from shea.ports.repositories import DecisionRepository, ToolExecutionRepository
from shea.ports.unit_of_work import UnitOfWork
from shea.recovery.idempotency import IdempotencyKeyGenerator
from shea.security.service import SecurityService
from shea.tools.executor import CapabilityNotAuthorizedError, ToolExecutor

_ADVANCE_EVENT_BY_OUTCOME: dict[ExecutionOutcome, str] = {
    ExecutionOutcome.SUCCESS: "execution_complete",
    ExecutionOutcome.FAILURE: "execution_failed",
    ExecutionOutcome.UNKNOWN: "execution_unknown",
}


class TaskNotRunningError(Exception):
    def __init__(self, task_id: str, actual_state: TaskState) -> None:
        self.task_id = task_id
        self.actual_state = actual_state
        super().__init__(
            f"Task {task_id!r} is not RUNNING (currently {actual_state.value!r}); "
            "execution can only start from RUNNING, reached via DecisionService."
        )


class MissingDecisionError(Exception):
    """Raised if a task reached RUNNING without a persisted Decision.

    This should be structurally impossible given the current pipeline —
    only DecisionService can transition a task into RUNNING, and it
    always persists a Decision first — but ExecutionService checks
    anyway rather than trusting that invariant silently, per research doc
    Section 15.27's determinism requirement for security-sensitive
    components.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(
            f"Task {task_id!r} is RUNNING but has no persisted Decision; "
            "cannot determine authorized capabilities."
        )


class DuplicateExecutionSuppressedError(Exception):
    """Raised instead of re-invoking a tool handler when a prior
    execution with the same idempotency key already reported SUCCESS or
    UNKNOWN.

    Research doc Section 8.15 / Core Principle #17: "Provider retry must
    not automatically imply tool re-execution" — a SUCCESS means the
    side effect already happened; UNKNOWN means it might have (Appendix
    B: EXECUTION SUCCESS != VERIFIED SUCCESS cuts both ways — an
    unconfirmed outcome is not license to just try again). A prior
    FAILURE is NOT suppressed: by definition no side effect is claimed
    to have occurred, so a genuine retry is safe to attempt.
    """

    def __init__(
        self,
        task_id: str,
        tool: str,
        action: str,
        idempotency_key: str,
        prior_outcome: ExecutionOutcome,
    ) -> None:
        self.task_id = task_id
        self.tool = tool
        self.action = action
        self.idempotency_key = idempotency_key
        self.prior_outcome = prior_outcome
        super().__init__(
            f"Task {task_id!r} tool {tool!r}.{action!r} already has a "
            f"{prior_outcome.value} execution on record for idempotency "
            f"key {idempotency_key!r}; refusing to re-invoke the handler "
            "rather than risk duplicating a side effect that may have "
            "already occurred."
        )


@dataclass(frozen=True)
class ExecutionOutcomeRecord:
    response: ToolResponse
    outcome: ExecutionOutcome
    task: Task


class ExecutionService:
    """Technical doc Component: Execution Runtime, restricted to the
    "run one already-authorized, security-cleared tool call and advance
    the task accordingly" slice of that responsibility. The actual
    sandboxing mechanics (timeout, redaction) live in whatever
    ExecutionBoundary the injected ToolExecutor uses — this service does
    not implement isolation itself, it sequences the pipeline stages
    around it.

    `security_service` is REQUIRED, not optional. Phases 1-7 defaulted it
    to None (skipping the check) so tests could construct ExecutionService
    without one — that made security enforcement a convention rather than
    a mechanical guarantee, the exact gap the Phase 8 audit flagged: "the
    comment explicitly says production wiring should provide it, but
    that's a convention, not an architectural guarantee." There is no
    execute() path that can run a tool without a SecurityService.enforce()
    call happening first.

    Looks up the task's authorized capabilities from the persisted
    Decision (never from a caller-supplied value), so a capability check
    here reflects what was actually authorized, not what someone claims
    was authorized.

    Also computes an `IdempotencyKeyGenerator` key from (task, tool,
    action, arguments) before every attempt and checks it against prior
    `ToolExecutionRecord`s. A prior SUCCESS or UNKNOWN for the same key
    raises `DuplicateExecutionSuppressedError` instead of invoking the
    handler again — same gap class as `security_service` above:
    `IdempotencyKeyGenerator` existed, was unit-tested, and was never
    actually called from here until Phase 8.
    """

    def __init__(
        self,
        *,
        tool_executor: ToolExecutor,
        orchestrator: Orchestrator,
        decision_repository: DecisionRepository,
        tool_execution_repository: ToolExecutionRepository,
        audit: AuditRecorder,
        id_generator: IdGenerator,
        security_service: SecurityService,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._tool_executor = tool_executor
        self._orchestrator = orchestrator
        self._decisions = decision_repository
        self._tool_executions = tool_execution_repository
        self._audit = audit
        self._ids = id_generator
        self._security = security_service
        self._uow = unit_of_work

    def execute(self, task: Task, request: ToolRequest) -> ExecutionOutcomeRecord:
        if task.state is not TaskState.RUNNING:
            raise TaskNotRunningError(task.id, task.state)

        # Raises SecurityViolationError and drives the task to
        # SECURITY_HALT itself on a violation; nothing further to do here
        # on that path except let the exception propagate. Unconditional
        # — there is no flag or default that skips this call.
        self._security.enforce(task, request)

        # Same logical operation (task/tool/action/arguments) always
        # produces the same key, so a retry of an already-attempted call
        # is detectable before the handler is ever reached — not just
        # unit-tested in isolation (see Phase 8 review for the gap this
        # closes).
        idempotency_key = IdempotencyKeyGenerator.generate(
            task_id=task.id,
            tool=request.tool,
            action=request.action,
            arguments=request.arguments,
        )
        prior = self._tool_executions.get_by_idempotency_key(idempotency_key)
        if prior is not None and prior.outcome in (
            ExecutionOutcome.SUCCESS,
            ExecutionOutcome.UNKNOWN,
        ):
            self._audit.record(
                actor="execution_service",
                component="execution.tool",
                event_type="execution.duplicate_suppressed",
                action=request.action,
                result="suppressed",
                request_id=task.request_id,
                task_id=task.id,
                metadata={
                    "tool": request.tool,
                    "idempotency_key": idempotency_key,
                    "prior_outcome": prior.outcome.value,
                },
            )
            raise DuplicateExecutionSuppressedError(
                task.id, request.tool, request.action, idempotency_key, prior.outcome
            )

        decision = self._decisions.get_by_task(task.id)
        if decision is None:
            raise MissingDecisionError(task.id)

        authorized_capabilities = frozenset(decision.capabilities)

        try:
            result = self._tool_executor.execute(request, authorized_capabilities)
        except CapabilityNotAuthorizedError as exc:
            with self._uow:
                self._audit.record(
                    actor="execution_service",
                    component="execution.tool",
                    event_type="execution.capability_denied",
                    action=request.action,
                    result="denied",
                    request_id=task.request_id,
                    task_id=task.id,
                    metadata={
                        "tool": request.tool,
                        "missing": sorted(exc.missing_capabilities),
                    },
                )
                self._tool_executions.save(
                    ToolExecutionRecord(
                        id=self._ids.new_id(),
                        task_id=task.id,
                        tool=request.tool,
                        action=request.action,
                        outcome=ExecutionOutcome.FAILURE,
                        success=False,
                        error=str(exc),
                        idempotency_key=idempotency_key,
                    )
                )
            failed_task = self._orchestrator.advance(task.id, "execution_failed")
            return ExecutionOutcomeRecord(
                response=ToolResponse(success=False, error=str(exc)),
                outcome=ExecutionOutcome.FAILURE,
                task=failed_task,
            )

        with self._uow:
            self._tool_executions.save(
                ToolExecutionRecord(
                    id=self._ids.new_id(),
                    task_id=task.id,
                    tool=request.tool,
                    action=request.action,
                    outcome=result.outcome,
                    success=result.response.success,
                    data=result.response.data,
                    error=result.response.error,
                    idempotency_key=idempotency_key,
                )
            )

            self._audit.record(
                actor="execution_service",
                component="execution.tool",
                event_type=f"execution.{result.outcome.value.lower()}",
                action=request.action,
                result=result.outcome.value.lower(),
                request_id=task.request_id,
                task_id=task.id,
                metadata={"tool": request.tool, "success": result.response.success},
            )

        event = _ADVANCE_EVENT_BY_OUTCOME[result.outcome]
        advanced_task = self._orchestrator.advance(task.id, event)

        return ExecutionOutcomeRecord(
            response=result.response, outcome=result.outcome, task=advanced_task
        )