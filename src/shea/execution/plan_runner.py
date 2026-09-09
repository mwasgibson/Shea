# src/shea/execution/plan_runner.py
from __future__ import annotations

from dataclasses import dataclass

from shea.contracts.enums import ExecutionOutcome, TaskState
from shea.contracts.models import Task, ToolRequest
from shea.decision.service import DecisionService
from shea.execution.service import ExecutionOutcomeRecord, ExecutionService
from shea.ports.repositories import PlanRepository
from shea.security.service import SecurityService
from shea.tools.registry import ToolRegistry
from shea.verification.service import VerificationService


@dataclass(frozen=True)
class PlanRunResult:
    task: Task
    step_results: tuple[ExecutionOutcomeRecord, ...]
    completed_steps: int
    stopped_early: bool


class PlanRunner:
    """Execute a plan step-by-step with per-step authorization binding.

    For each step (in order):
      READY  --authorize_and_run(bound to step)--> RUNNING
           --execute--> VERIFYING
           --verify(more_steps=...)--> READY | COMPLETED | FAILED

    Intermediate successful steps use step_verified → READY.
    The last successful step uses verified → COMPLETED.
    """

    def __init__(
        self,
        *,
        decision_service: DecisionService,
        execution_service: ExecutionService,
        verification_service: VerificationService,
        security_service: SecurityService,
        plan_repository: PlanRepository,
        tool_registry: ToolRegistry,
    ) -> None:
        self._decision = decision_service
        self._execution = execution_service
        self._verification = verification_service
        self._security = security_service
        self._plans = plan_repository
        self._tools = tool_registry

    def run(
        self,
        task: Task,
        *,
        acting_user: str = "user",
        explicit_user_ack: bool = True,
    ) -> PlanRunResult:
        plan = self._plans.get_by_task(task.id)
        if plan is None:
            raise ValueError(f"Task {task.id!r} has no persisted plan")

        steps = [s for s in sorted(plan.steps, key=lambda s: s.order) if s.tool]
        if not steps:
            raise ValueError(f"Plan for task {task.id!r} has no executable steps")

        results: list[ExecutionOutcomeRecord] = []
        current = task
        stopped_early = False

        for index, step in enumerate(steps):
            more_steps = index < len(steps) - 1

            # Task must be READY (first step after planning, or after step_verified)
            if current.state is not TaskState.READY:
                raise RuntimeError(
                    f"PlanRunner expected READY before step {step.id!r}, "
                    f"got {current.state.value!r}"
                )

            capabilities = self._tools.get_declaration(step.tool).capabilities
            decision_outcome = self._decision.evaluate_and_authorize(
                current,
                capabilities=capabilities,
                plan=plan,
                step=step,
                arguments=dict(step.arguments),
                acting_user=acting_user,
                explicit_user_ack=explicit_user_ack,
            )
            current = decision_outcome.task

            request = ToolRequest(
                request_id=current.request_id,
                tool=step.tool,
                action=step.description or step.tool,
                arguments=dict(step.arguments),
            )
            exec_result = self._execution.execute(current, request)
            results.append(exec_result)
            current = exec_result.task

            if exec_result.outcome is not ExecutionOutcome.SUCCESS:
                stopped_early = True
                break

            if current.state is not TaskState.VERIFYING:
                stopped_early = True
                break

            scan = self._security.scan_output(
                current, step.tool, exec_result.response.data
            )
            if scan.flagged:
                # Quarantine: do not continue with tainted output
                stopped_early = True
                break

            ver = self._verification.verify(current, more_steps=more_steps)
            current = ver.task
            if not ver.verification.verified:
                stopped_early = True
                break

            # more_steps=True → READY; more_steps=False → COMPLETED
            if not more_steps:
                break

        return PlanRunResult(
            task=current,
            step_results=tuple(results),
            completed_steps=len(results),
            stopped_early=stopped_early
            or current.state is not TaskState.COMPLETED,
        )