from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shea.contracts.enums import TaskState
from shea.contracts.models import Decision, Plan, Task
from shea.core.orchestrator import Orchestrator
from shea.execution.plan_runner import PlanRunner, PlanRunResult
from shea.observability.context import active_context
from shea.planning.service import PlanningOutcome, PlanningService


@dataclass(frozen=True)
class InteractionResult:
    """One user request through planning + multi-step execution."""

    planning: PlanningOutcome | None
    run: PlanRunResult | None
    task: Task
    error: str | None = None
    pending_decision: Decision | None = None
    needs_confirmation: bool = False
    confirmation: dict[str, Any] | None = None


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
        orchestrator: Orchestrator,
    ) -> None:
        self._planning = planning_service
        self._runner = plan_runner
        self._orchestrator = orchestrator

    def handle_text(
        self,
        text: str,
        *,
        session_id: str = "cli",
        explicit_user_ack: bool = True,
        actor: str = "user",
        run: bool = True,
        profile_id: str = "system",
    ) -> InteractionResult:
        try:
            planning = self._planning.create_and_plan(
                session_id=session_id,
                request_text=text,
                actor=actor,
                profile_id=profile_id,
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            # Phase E Fault Tolerance: Do not crash the entire interaction layer if LLM fails
            # We construct a synthetic planning failure result
            import uuid
            from datetime import UTC, datetime

            from shea.contracts.models import Intent, Task
            from shea.planning.service import PlanningOutcome

            # Bare minimum synthetic task just to hold the error state
            task_id = uuid.uuid4().hex
            synthetic_task = Task(
                id=task_id,
                session_id=session_id,
                request_id=uuid.uuid4().hex,
                state=TaskState.FAILED,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC)
            )
            synthetic_intent = Intent(id=task_id, task_id=task_id, type="chat", goal=text, source="api", created_at=datetime.now(UTC))
            return InteractionResult(
                planning=PlanningOutcome(task=synthetic_task, intent=synthetic_intent, plan=Plan(id=task_id, task_id=task_id, objective=text, steps=[])),
                run=None,
                task=synthetic_task,
                error=f"Critical failure during planning: {e}"
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

        try:
            # Bind observability context before running the plan
            with active_context(correlation_id=task.request_id, task_id=task.id):
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
        except Exception as e:
            import traceback
            traceback.print_exc()
            # Catch catastrophic adapter crashes (e.g. C-level segfaults wrapped in RuntimeError)
            from shea.decision.exceptions import AuthorizationRequiredError
            if isinstance(e, AuthorizationRequiredError):
                return InteractionResult(
                    planning=planning,
                    run=None,
                    task=task,
                    error="authorization_required",
                    pending_decision=e.decision,
                )
            return InteractionResult(
                planning=planning, run=None, task=task,
                error=f"Critical failure during execution: {e}",
            )

    def confirm_and_run(
        self,
        task_id: str,
        *,
        actor: str = "user",
        explicit_user_ack: bool = True,
    ) -> InteractionResult:
        task: Task = self._orchestrator.get_task(task_id)
        result = self._runner.run(task, acting_user=actor, explicit_user_ack=explicit_user_ack)
        return InteractionResult(
            planning=None,
            run=result,
            task=result.task,
            needs_confirmation=False,
        )