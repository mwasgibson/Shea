from __future__ import annotations

from dataclasses import dataclass

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import ExecutionOutcome, TaskState
from shea.contracts.models import Task, ToolRequest, ToolResponse
from shea.core.orchestrator import Orchestrator
from shea.ports.repositories import DecisionRepository
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


@dataclass(frozen=True)
class ExecutionOutcomeRecord:
    response: ToolResponse
    outcome: ExecutionOutcome
    task: Task


class ExecutionService:
    """Technical doc Component: Execution Runtime, restricted to the
    "run one already-authorized tool call and advance the task
    accordingly" slice of that responsibility. Sandboxing, resource
    limits, and network/filesystem scoping (research doc Section 10) are
    NOT implemented here — this is the orchestration layer around them,
    not the isolation boundary itself.

    Looks up the task's authorized capabilities from the persisted
    Decision (never from a caller-supplied value), so a capability check
    here reflects what was actually authorized, not what someone claims
    was authorized.
    """

    def __init__(
        self,
        *,
        tool_executor: ToolExecutor,
        orchestrator: Orchestrator,
        decision_repository: DecisionRepository,
        audit: AuditRecorder,
    ) -> None:
        self._tool_executor = tool_executor
        self._orchestrator = orchestrator
        self._decisions = decision_repository
        self._audit = audit

    def execute(self, task: Task, request: ToolRequest) -> ExecutionOutcomeRecord:
        if task.state is not TaskState.RUNNING:
            raise TaskNotRunningError(task.id, task.state)

        decision = self._decisions.get_by_task(task.id)
        if decision is None:
            raise MissingDecisionError(task.id)

        authorized_capabilities = frozenset(decision.capabilities)

        try:
            result = self._tool_executor.execute(request, authorized_capabilities)
        except CapabilityNotAuthorizedError as exc:
            self._audit.record(
                actor="execution_service",
                component="execution.tool",
                event_type="execution.capability_denied",
                action=request.action,
                result="denied",
                request_id=task.request_id,
                task_id=task.id,
                metadata={"tool": request.tool, "missing": sorted(exc.missing_capabilities)},
            )
            failed_task = self._orchestrator.advance(task.id, "execution_failed")
            return ExecutionOutcomeRecord(
                response=ToolResponse(success=False, error=str(exc)),
                outcome=ExecutionOutcome.FAILURE,
                task=failed_task,
            )

        event = _ADVANCE_EVENT_BY_OUTCOME[result.outcome]
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
        advanced_task = self._orchestrator.advance(task.id, event)

        return ExecutionOutcomeRecord(
            response=result.response, outcome=result.outcome, task=advanced_task
        )