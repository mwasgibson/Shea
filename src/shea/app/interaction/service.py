from __future__ import annotations

from dataclasses import dataclass

from shea.execution.plan_runner import PlanRunner, PlanRunResult
from shea.planning.service import PlanningOutcome, PlanningService


@dataclass(frozen=True)
class InteractionResult:
    planning: PlanningOutcome
    execution: PlanRunResult


class InteractionService:
    """Public request boundary that keeps interaction on the safety pipeline."""

    def __init__(
        self,
        *,
        planning_service: PlanningService,
        plan_runner: PlanRunner,
    ) -> None:
        self._planning = planning_service
        self._runner = plan_runner

    def submit_text(
        self,
        *,
        session_id: str,
        text: str,
        actor: str = "user",
        explicit_user_ack: bool = True,
    ) -> InteractionResult:
        planning = self._planning.create_and_plan(
            session_id=session_id,
            request_text=text,
            actor=actor,
            source="text",
        )
        execution = self._runner.run(
            planning.task,
            acting_user=actor,
            explicit_user_ack=explicit_user_ack,
        )
        return InteractionResult(planning=planning, execution=execution)
