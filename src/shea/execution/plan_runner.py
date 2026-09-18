from __future__ import annotations

from dataclasses import dataclass

from shea.contracts.enums import ExecutionOutcome, TaskState
from shea.contracts.models import Plan, PlanStep, Task, ToolRequest
from shea.decision.service import DecisionService
from shea.execution.service import ExecutionOutcomeRecord, ExecutionService
from shea.ports.repositories import PlanRepository
from shea.profiles.snapshot import ProfileSnapshot
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



def sort_steps_topologically(steps: list[PlanStep]) -> list[PlanStep]:
    step_dict: dict[str, PlanStep] = {s.id: s for s in steps}
    
    # dependencies: map step_id -> set of prerequisite step_ids
    # We only care about dependencies that are actually executable (have a tool)
    executable_ids: set[str] = set(step_dict.keys())
    
    dependencies: dict[str, set[str]] = {}
    for s in steps:
        deps: set[str] = set()
        for dep in getattr(s, "depends_on", []):
            if isinstance(dep, str) and dep in executable_ids:
                deps.add(dep)
        dependencies[s.id] = deps

    ordered_step_ids: list[str] = []
    
    while dependencies:
        # Find all steps that have no unmet prerequisites
        ready_ids: list[str] = [sid for sid, d in dependencies.items() if not d]
        
        if not ready_ids:
            # We have steps left, but none are ready. Graph has a cycle.
            raise ValueError("Plan step dependencies contain a cycle or unresolved edge")
            
        # Tie-break deterministic execution by fallback `order` field
        def _get_order(sid: str) -> int:
            return step_dict[sid].order
            
        ready_ids.sort(key=_get_order)
        
        # We can theoretically execute all ready_ids in parallel.
        # But this PlanRunner processes them sequentially. We will just pick the first one
        # or we could append all of them. Since we process sequentially, let's just 
        # add all of them into the queue.
        for ready_id in ready_ids:
            ordered_step_ids.append(ready_id)
            del dependencies[ready_id]
            for deps_set in dependencies.values():
                deps_set.discard(ready_id)
                
    return [step_dict[sid] for sid in ordered_step_ids]

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

        executable_steps = [s for s in plan.steps if s.tool]
        steps = sort_steps_topologically(executable_steps)
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
                snapshot_params = {"_profile_snapshot": current.profile_snapshot} if current.profile_snapshot else {}
                snapshot = ProfileSnapshot.from_parameters(snapshot_params)
                decision_outcome = self._decision.evaluate_and_authorize(
                    current,
                    capabilities=capabilities,
                    plan=plan,
                    step=step,
                    arguments=dict(step.arguments),
                    acting_user=acting_user,
                    explicit_user_ack=explicit_user_ack,
                    profile_id=snapshot.profile_id,
                )
                current = decision_outcome.task

                request = ToolRequest(
                    request_id=current.request_id,
                    tool=step.tool,
                    action = getattr(step, "action", None) or step.description or step.tool,
                    arguments=dict(step.arguments),
                )
                exec_result = self._execution.execute(current, request)
                results.append(exec_result)
                current = exec_result.task

                if exec_result.outcome is not ExecutionOutcome.SUCCESS:
                    self._set_step_state(plan, step, STEP_FAILED)
                    stopped_early = True
                    break

                if current.state is not TaskState.VERIFYING:
                    self._set_step_state(plan, step, STEP_FAILED)
                    stopped_early = True
                    break

                scan = self._security.scan_output(
                    current, step.tool, exec_result.response.data if exec_result.response else None
                )
                if scan.flagged:
                    self._set_step_state(plan, step, STEP_FAILED)
                    stopped_early = True
                    break

                ver = self._verification.verify(current, more_steps=more_steps)
                current = ver.task

                if not ver.verification.verified:
                    self._set_step_state(plan, step, STEP_FAILED)
                    stopped_early = True
                    break

                self._set_step_state(plan, step, STEP_COMPLETED)
                completed_count += 1

            except Exception as err:
                print(f"\n {type(err).__name__}: {err}")
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