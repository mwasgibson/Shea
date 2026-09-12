from __future__ import annotations

from dataclasses import dataclass

from shea.app.adapters.tool_executor import ToolExecutorAdapter
from shea.app.contracts import ExecutionContract
from shea.app.supervisor import ExecutionSupervisor
from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import ExecutionOutcome, TaskState
from shea.contracts.models import Task, ToolExecutionRecord, ToolRequest, ToolResponse
from shea.core.orchestrator import Orchestrator
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.repositories import (
    AuthorizationRepository,
    DecisionRepository,
    PlanRepository,
    ToolExecutionRepository,
)
from shea.ports.unit_of_work import UnitOfWork
from shea.recovery.idempotency import IdempotencyKeyGenerator
from shea.security.binding import (
    compute_arguments_hash,
    compute_plan_hash,
    compute_step_hash,
)
from shea.security.exceptions import (
    AuthorizationAlreadyUsedError,
    AuthorizationBindingMismatchError,
    AuthorizationExpiredError,
)
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
        execution_supervisor: ExecutionSupervisor,
        orchestrator: Orchestrator,
        decision_repository: DecisionRepository,
        authorization_repository: AuthorizationRepository,
        plan_repository: PlanRepository,
        tool_execution_repository: ToolExecutionRepository,
        audit: AuditRecorder,
        id_generator: IdGenerator,
        security_service: SecurityService,
        unit_of_work: UnitOfWork,
        clock: Clock,
    ) -> None:
        self._tool_executor = tool_executor
        self._execution_supervisor = execution_supervisor
        self._orchestrator = orchestrator
        self._decisions = decision_repository
        self._tool_executions = tool_execution_repository
        self._authorizations = authorization_repository
        self._plans = plan_repository
        self._audit = audit
        self._ids = id_generator
        self._security = security_service
        self._uow = unit_of_work
        self._clock = clock
        self._execution_supervisor.ensure_adapter(ToolExecutorAdapter(tool_executor))
        
    @staticmethod
    def _map_app_outcome(outcome: object) -> ExecutionOutcome:
        value = getattr(outcome, "value", str(outcome))

        mapping = {
            "SUCCESS": ExecutionOutcome.SUCCESS,
            "FAILURE": ExecutionOutcome.FAILURE,
            "UNKNOWN": ExecutionOutcome.UNKNOWN,
        }

        try:
            return mapping[str(value).upper()]
        except KeyError as exc:
            raise RuntimeError(
                f"Unsupported app execution outcome: {value!r}"
            ) from exc

    def execute(self, task: Task, request: ToolRequest) -> ExecutionOutcomeRecord:
        if task.state is not TaskState.RUNNING:
            raise TaskNotRunningError(task.id, task.state)

        # Raises SecurityViolationError and drives the task to
        # SECURITY_HALT itself on a violation; nothing further to do here
        # on that path except let the exception propagate. Unconditional
        # — there is no flag or default that skips this call.
        self._security.enforce(task, request)
        self._verify_authorization_binding(task, request)

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
            self._tool_executor.validate_capabilities(request, authorized_capabilities)
        except CapabilityNotAuthorizedError as exc:
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
                    "missing_capabilities": sorted(exc.missing_capabilities),
                },
            )
            raise

        authorization = self._authorizations.list_by_task(task.id)[-1]

        contract = ExecutionContract(
            contract_id=self._ids.new_id(),
            authorization_id=authorization.id,
            capability=(
                sorted(authorized_capabilities)[0]
                if authorized_capabilities
                else f"tool.{request.tool}"
            ),
            operation=f"tool.{request.tool}.{request.action}",
            target=request.tool,
            arguments=dict(request.arguments),
            expires_at=authorization.expires_at,
            metadata={
                "execution_backend": "tool_executor",
                "tool": request.tool,
                "action": request.action,
                "request_id": request.request_id,
                "task_id": task.id,
                "tool_context": dict(request.context),
                "_authorized_capabilities": tuple(
                    sorted(authorized_capabilities)
                ),
                "idempotency_key": idempotency_key,
            },
        )

        supervision = self._execution_supervisor.execute(contract)
        raw_evidence = supervision.adapter_result.evidence or {}
        # ToolExecutorAdapter puts handler payload under "data"; native adapters may not
        evidence_data = raw_evidence.get("data", raw_evidence)

        app_verification_result = (
            supervision.verification.result.value
            if supervision.verification is not None
            else None
        )

        response = ToolResponse(
            success=self._map_app_outcome(supervision.adapter_result.outcome)
            is ExecutionOutcome.SUCCESS,
            data=evidence_data,
            error=supervision.adapter_result.error,
            metadata={
                "receipt_id": supervision.receipt.id,
                "attempt_id": supervision.attempt.id,
                "evidence_id": supervision.evidence_id,
                "app_verification_result": app_verification_result,
                "app_verification_explanation": (
                    supervision.verification.explanation
                    if supervision.verification is not None
                    else None
                ),
            },
        )

        response = ToolResponse(
            success=self._map_app_outcome(
                supervision.adapter_result.outcome
            )
            is ExecutionOutcome.SUCCESS,
            data=supervision.adapter_result.evidence.get("data"),
            error=supervision.adapter_result.error,
            metadata={
                "receipt_id": supervision.receipt.id,
                "attempt_id": supervision.attempt.id,
                "evidence_id": supervision.evidence_id,
            },
        )

        result = ExecutionOutcomeRecord(
            response=response,
            outcome=self._map_app_outcome(
                supervision.adapter_result.outcome
            ),
            task=task,
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
                    metadata=result.response.metadata,
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
                metadata={
                    "tool": request.tool,
                    "success": result.response.success,
                    "receipt_id": supervision.receipt.id,
                    "attempt_id": supervision.attempt.id,
                    "evidence_id": supervision.evidence_id,
                },
            )

            # Consume one-shot auth only on durable SUCCESS
            if result.outcome is ExecutionOutcome.SUCCESS:
                auths = self._authorizations.list_by_task(task.id)
                if auths:
                    auth = auths[-1]
                    if auth.nonce is not None and auth.used_at is None:
                        auth.used_at = self._clock.now()
                        self._authorizations.save(auth)

            advanced_task = self._orchestrator.advance(
                task.id,
                _ADVANCE_EVENT_BY_OUTCOME[result.outcome],
            )

        return ExecutionOutcomeRecord(
            response=result.response, outcome=result.outcome, task=advanced_task
        )
        
    def _verify_authorization_binding(self, task: Task, request: ToolRequest) -> None:
        """Verify that the authorization for this task matches the current request.

        Checks:
        1. Authorization exists for this task
        2. Plan hash matches (if authorization has a plan_hash)
        3. Step hash matches (if authorization has a step_hash)
        4. Arguments hash matches (if authorization has an arguments_hash)
        5. Authorization has not expired
        6. Authorization nonce has not been used (replay protection)
        """
        # Get the most recent authorization for this task
        authorizations = self._authorizations.list_by_task(task.id)
        if not authorizations:
            raise MissingDecisionError(task.id)

        auth = authorizations[-1]

        # Replay: already consumed
        if auth.used_at is not None:
            raise AuthorizationAlreadyUsedError(task.id, auth.nonce or "")

        # Expiry
        if auth.expires_at is not None and auth.expires_at < self._clock.now():
            raise AuthorizationExpiredError(task.id, auth.expires_at)

        current_plan = self._plans.get_by_task(task.id)

        if auth.plan_hash is not None:
            if current_plan is None:
                raise AuthorizationBindingMismatchError(
                    task.id, "plan", auth.plan_hash, None
                )
            current_plan_hash = compute_plan_hash(current_plan)
            if auth.plan_hash != current_plan_hash:
                raise AuthorizationBindingMismatchError(
                    task.id, "plan", auth.plan_hash, current_plan_hash
                )

        if auth.step_hash is not None:
            if current_plan is None:
                raise AuthorizationBindingMismatchError(
                    task.id, "step", auth.step_hash, None
                )
            matching_step = next(
                (
                    s
                    for s in current_plan.steps
                    if s.tool == request.tool and compute_step_hash(s) == auth.step_hash
                ),
                None,
            )
            if matching_step is None:
                # If no step has this exact hash, compute candidate hash for diagnostic
                candidate = next((s for s in current_plan.steps if s.tool == request.tool), None)
                candidate_hash = compute_step_hash(candidate) if candidate else None
                raise AuthorizationBindingMismatchError(
                    task.id, "step", auth.step_hash, candidate_hash
                )

        if auth.arguments_hash is not None:
            current_arguments_hash = compute_arguments_hash(request.arguments)
            if auth.arguments_hash != current_arguments_hash:
                raise AuthorizationBindingMismatchError(
                    task.id, "arguments", auth.arguments_hash, current_arguments_hash
                )              