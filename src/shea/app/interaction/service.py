from __future__ import annotations

from dataclasses import dataclass

from shea.contracts.enums import TaskState
from shea.contracts.models import Task
from shea.execution.plan_runner import PlanRunner, PlanRunResult
from shea.planning.service import PlanningOutcome, PlanningService


@dataclass(frozen=True)
class InteractionResult:
    """One user request through planning + multi-step execution."""

    planning: PlanningOutcome
    run: PlanRunResult | None
    task: Task
    error: str | None = None


class InteractionService:
    """Public boundary: raw text → READY plan → PlanRunner.

    Does not invent authority. Decision/auth still happen inside PlanRunner
    per step. explicit_user_ack is required for the run (whole-run ack).
    """

    def __init__(
        self,
        *,
        planning_service: PlanningService,
        plan_runner: PlanRunner,
    ) -> None:
        self._planning = planning_service
        self._runner = plan_runner

    def handle_text(
        self,
        text: str,
        *,
        session_id: str = "cli",
        explicit_user_ack: bool = True,
        actor: str = "user",
        run: bool = True,
    ) -> InteractionResult:
        planning = self._planning.create_and_plan(
            session_id=session_id,
            request_text=text,
        )
        task = planning.task
        if task.state is not TaskState.READY:
            return InteractionResult(
                planning=planning,
                run=None,
                task=task,
                error=f"planning left task in {task.state.value}, expected READY",
            )
        if not run:
            return InteractionResult(planning=planning, run=None, task=task)

        result = self._runner.run(
            task,
            acting_user=actor,
            explicit_user_ack=explicit_user_ack,
        )
        return InteractionResult(
            planning=planning,
            run=result,
            task=result.task,
        )