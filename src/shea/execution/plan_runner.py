from __future__ import annotations

from dataclasses import dataclass

from shea.contracts.enums import ExecutionOutcome, TaskState
from shea.contracts.models import Plan, PlanStep, Task, ToolRequest
from shea.decision.service import DecisionService
from shea.execution.service import ExecutionOutcomeRecord, ExecutionService
from shea.ports.repositories import PlanRepository
from shea.security.service import SecurityService
from shea.tools.registry import ToolRegistry
from shea.verification.service import VerificationService

# PlanStep.state values — durable, not only in-memory loop counters
STEP_PENDING = "PENDING"
STEP_RUNNING = "RUNNING"
STEP_COMPLETED = "COMPLETED"
STEP_FAILED = "FAILED"
STEP_SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class PlanRunResult:
    task: Task
    step_results: tuple[ExecutionOutcomeRecord, ...]
    completed_steps: int
    stopped_early: bool


class PlanRunner:
    """Execute a plan step-by-step with per-step authorization binding.

    For each pending step (in order):
      READY  --authorize_and_run(bound to this step)--> RUNNING
           --execute--> VERIFYING
           --verify(more_steps=...)--> READY | COMPLETED | FAILED

    Intermediate successful steps use ``step_verified`` → READY.
    The last successful step uses ``verified`` → COMPLETED.

    Each step gets its own Decision + Authorization (new nonce). Nonces
    are never reused across steps.

    Product rules:
    - Stop on execution failure / unknown
    - Stop on verification failure
    - Stop on security output scan flagged (injection quarantine)
    - Skip steps already COMPLETED (resume-friendly)
    - Persist PlanStep.state after each transition via PlanRepository
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

        steps = sorted(
            (s for s in plan.steps if s.tool),
            key=lambda s: s.order,
        )
        if not steps:
            raise ValueError(f"Plan for task {task.id!r} has no executable steps")

        results: list[ExecutionOutcomeRecord] = []
        current = task
        stopped_early = False
        completed_count = 0

        # Indices of steps that still need work (not already COMPLETED)
        pending_indices = [
            i for i, s in enumerate(steps) if s.state != STEP_COMPLETED
        ]
        if not pending_indices:
            return PlanRunResult(
                task=current,
                step_results=(),
                completed_steps=len(steps),
                stopped_early=False,
            )

        for position, index in enumerate(pending_indices):
            step = steps[index]
            is_last_pending = position == len(pending_indices) - 1
            more_steps = not is_last_pending

            if current.state is not TaskState.READY:
                raise RuntimeError(
                    f"PlanRunner expected READY before step {step.id!r}, "
                    f"got {current.state.value!r}"
                )

            try:
                self._set_step_state(plan, step, STEP_RUNNING)

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
                    print(f"\n[DEBUG] Execution failed: {exec_result.response.error}")
                    self._set_step_state(plan, step, STEP_FAILED)
                    stopped_early = True
                    break

                if current.state is not TaskState.VERIFYING:
                    print(f"\n[DEBUG] Task not VERIFYING after execute: {current.state}")
                    self._set_step_state(plan, step, STEP_FAILED)
                    stopped_early = True
                    break

                scan = self._security.scan_output(
                    current, step.tool, exec_result.response.data if exec_result.response else None
                )
                if scan.flagged:
                    print(f"\n[DEBUG] Security scan flagged: {scan.reason}")
                    self._set_step_state(plan, step, STEP_FAILED)
                    stopped_early = True
                    break

                ver = self._verification.verify(current, more_steps=more_steps)
                current = ver.task

                if not ver.verification.verified:
                    print(f"\n[DEBUG] Verification rejected: {ver.verification.explanation}")
                    self._set_step_state(plan, step, STEP_FAILED)
                    stopped_early = True
                    break

                self._set_step_state(plan, step, STEP_COMPLETED)
                completed_count += 1

            except Exception as err:
                print(f"\n[DEBUG EXCEPTION IN STEP]: {type(err).__name__}: {err}")
                self._set_step_state(plan, step, STEP_FAILED)
                stopped_early = True
                break

            if not more_steps:
                break

        return PlanRunResult(
            task=current,
            step_results=tuple(results),
            completed_steps=completed_count,
            stopped_early=stopped_early or current.state is not TaskState.COMPLETED,
        )

    def _set_step_state(self, plan: Plan, step: PlanStep, state: str) -> None:
        step.state = state
        self._plans.save(plan)