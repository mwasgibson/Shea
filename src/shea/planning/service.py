from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from shea.audit.recorder import AuditRecorder
from shea.contracts.models import Intent, Plan, PlanStep, Request, Task
from shea.core.orchestrator import Orchestrator
from shea.model.exceptions import MalformedModelOutputError
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.model_provider import ModelProvider
from shea.ports.repositories import IntentRepository, PlanRepository
from shea.tools.registry import ToolRegistry
from shea.understanding.deterministic import DeterministicIntentMatcher, IntentDraft
from shea.understanding.exceptions import AmbiguousIntentError
from shea.understanding.parser import DEFAULT_CONFIDENCE_THRESHOLD, IntentParser

from .exceptions import PlanValidationError
from .templates import PlanTemplateRegistry, StepBlueprint
from .validator import validate_plan


def _build_plan_prompt(intent: Intent) -> str:
    return (
        "Produce a JSON object with a 'steps' array to accomplish this goal. "
        "Each step must have 'tool', 'action', and optionally 'arguments' and "
        f"'description'.\n\nGoal: {intent.goal}"
    )


def _blueprints_from_model_data(data: object) -> list[StepBlueprint]:
    if not isinstance(data, dict) or "steps" not in data:
        raise MalformedModelOutputError("model plan response missing 'steps'")

    payload = cast(dict[str, Any], data)
    steps_data = payload.get("steps")

    if not isinstance(steps_data, list) or not steps_data:
        raise MalformedModelOutputError("model plan response 'steps' must be a non-empty list")

    typed_steps = cast(list[object], steps_data)
    blueprints: list[StepBlueprint] = []

    for index, raw_step in enumerate(typed_steps):
        if not isinstance(raw_step, dict) or "tool" not in raw_step or "action" not in raw_step:
            raise MalformedModelOutputError(
                f"model plan step {index} missing required 'tool'/'action' fields"
            )

        step = cast(dict[str, Any], raw_step)
        raw_args = step.get("arguments", {})
        parsed_arguments = cast(dict[str, Any], raw_args) if isinstance(raw_args, dict) else {}

        blueprints.append(
            StepBlueprint(
                tool=str(step["tool"]),
                action=str(step["action"]),
                arguments=parsed_arguments,
                description=str(step.get("description", "")),
            )
        )
    return blueprints


@dataclass(frozen=True)
class PlanningOutcome:
    task: Task
    intent: Intent
    plan: Plan


class PlanningService:
    """Integration layer for research doc Section 6's "Intent
    Understanding & Planning" (treated as one subsystem in the docs, so
    treated as one service here). The only caller of
    `Orchestrator.advance(task_id, "start_planning" | "plan_ready" |
    "plan_failed" | "block")` and `Orchestrator.attach_plan()`.

    Pipeline:

        Request
            |
            v
        Orchestrator.create_task + advance("start_planning")
            |
            v
        IntentParser.parse()  --ambiguous--> block, re-raise
            |                 --malformed---> plan_failed, re-raise
            v
        persist Intent
            |
            v
        PlanTemplateRegistry.build()  (deterministic)
            | no template matched
            v
        model fallback  --malformed--> plan_failed, re-raise
            |
            v
        assemble Plan, validate_plan()  --invalid--> plan_failed, re-raise
            |
            v
        persist Plan, attach_plan(), advance("plan_ready")
    """

    def __init__(
        self,
        *,
        orchestrator: Orchestrator,
        deterministic_matcher: DeterministicIntentMatcher,
        template_registry: PlanTemplateRegistry,
        tool_registry: ToolRegistry,
        intent_repository: IntentRepository,
        plan_repository: PlanRepository,
        audit: AuditRecorder,
        clock: Clock,
        id_generator: IdGenerator,
        model_provider: ModelProvider | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._orchestrator = orchestrator
        self._intent_parser = IntentParser(
            deterministic_matcher, model_provider, confidence_threshold
        )
        self._templates = template_registry
        self._tools = tool_registry
        self._intents = intent_repository
        self._plans = plan_repository
        self._audit = audit
        self._clock = clock
        self._ids = id_generator
        self._model = model_provider

    def create_and_plan(
        self, *, session_id: str, request_text: str, actor: str = "user"
    ) -> PlanningOutcome:
        request = Request(
            request_id=self._ids.new_id(),
            session_id=session_id,
            actor=actor,
            input=request_text,
            source="text",
            created_at=self._clock.now(),
        )
        task = self._orchestrator.create_task(
            session_id=session_id, request_id=request.request_id
        )
        task = self._orchestrator.advance(task.id, "start_planning")

        draft = self._parse_intent(task, request_text)
        intent = self._persist_intent(task, draft)
        plan = self._build_and_validate_plan(task, intent, draft)

        self._plans.save(plan)
        self._orchestrator.attach_plan(task.id, plan.id)
        ready_task = self._orchestrator.advance(task.id, "plan_ready")

        self._audit.record(
            actor="planning_service",
            component="planning.engine",
            event_type="planning.plan_ready",
            action="create_and_plan",
            result="success",
            request_id=request.request_id,
            task_id=task.id,
            metadata={"plan_id": plan.id, "step_count": len(plan.steps)},
        )

        return PlanningOutcome(task=ready_task, intent=intent, plan=plan)

    def _parse_intent(self, task: Task, request_text: str) -> IntentDraft:
        try:
            return self._intent_parser.parse(request_text)
        except AmbiguousIntentError as exc:
            self._audit.record(
                actor="planning_service",
                component="understanding.engine",
                event_type="understanding.ambiguous",
                action="parse_intent",
                result="blocked",
                request_id=task.request_id,
                task_id=task.id,
                metadata={"confidence": exc.draft.confidence, "goal": exc.draft.goal},
            )
            self._orchestrator.advance(task.id, "block")
            raise
        except MalformedModelOutputError as exc:
            self._audit.record(
                actor="planning_service",
                component="understanding.engine",
                event_type="understanding.malformed_output",
                action="parse_intent",
                result="failed",
                request_id=task.request_id,
                task_id=task.id,
                metadata={"error": str(exc)},
            )
            self._orchestrator.advance(task.id, "plan_failed")
            raise

    def _persist_intent(self, task: Task, draft: IntentDraft) -> Intent:
        intent = Intent(
            id=self._ids.new_id(),
            task_id=task.id,
            type=draft.type,
            goal=draft.goal,
            parameters=draft.parameters,
            confidence=draft.confidence,
            source=draft.source,
            created_at=self._clock.now(),
        )
        self._intents.save(intent)
        self._audit.record(
            actor="planning_service",
            component="understanding.engine",
            event_type="understanding.intent_parsed",
            action="parse_intent",
            result="success",
            request_id=task.request_id,
            task_id=task.id,
            metadata={
                "type": intent.type,
                "confidence": intent.confidence,
                "source": intent.source,
            },
        )
        return intent

    def _build_and_validate_plan(self, task: Task, intent: Intent, draft: IntentDraft) -> Plan:
        blueprints = self._templates.build(intent.type, draft)

        try:
            if blueprints is None:
                blueprints = self._plan_from_model(intent)

            plan_id = self._ids.new_id()
            steps = [
                PlanStep(
                    id=self._ids.new_id(),
                    plan_id=plan_id,
                    order=index,
                    description=blueprint.description,
                    tool=blueprint.tool,
                    arguments=blueprint.arguments,
                )
                for index, blueprint in enumerate(blueprints)
            ]
            plan = Plan(id=plan_id, task_id=task.id, objective=intent.goal, steps=steps)
            validate_plan(plan, self._tools)
        except (MalformedModelOutputError, PlanValidationError) as exc:
            self._audit.record(
                actor="planning_service",
                component="planning.engine",
                event_type="planning.invalid_plan",
                action="build_plan",
                result="failed",
                request_id=task.request_id,
                task_id=task.id,
                metadata={"error": str(exc)},
            )
            self._orchestrator.advance(task.id, "plan_failed")
            raise

        return plan

    def _plan_from_model(self, intent: Intent) -> list[StepBlueprint]:
        if self._model is None:
            raise PlanValidationError(
                intent.task_id, "no plan template matched and no model provider configured"
            )
        response = self._model.generate(_build_plan_prompt(intent))
        return _blueprints_from_model_data(response.structured_data)