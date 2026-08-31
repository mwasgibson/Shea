from __future__ import annotations

import sqlite3

import pytest

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import TaskState
from shea.contracts.models import ModelResponse, ToolRequest, ToolResponse
from shea.core.orchestrator import Orchestrator
from shea.model.exceptions import MalformedModelOutputError
from shea.model.scripted import ScriptedModelProvider
from shea.persistence.sqlite.intent_repository import SqliteIntentRepository
from shea.persistence.sqlite.plan_repository import SqlitePlanRepository
from shea.planning.exceptions import PlanValidationError
from shea.planning.service import PlanningOutcome, PlanningService
from shea.planning.templates import PlanTemplateRegistry, StepBlueprint
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.tools.registry import ToolDeclaration, ToolRegistry
from shea.understanding.deterministic import DeterministicIntentMatcher, IntentDraft
from shea.understanding.exceptions import AmbiguousIntentError


def _never_called_handler(request: ToolRequest) -> ToolResponse:
    raise AssertionError("handler should never be invoked during planning")


def register_weather_tool(tool_registry: ToolRegistry) -> None:
    tool_registry.register(
        ToolDeclaration(name="weather", capabilities=frozenset({"network.connect"})),
        _never_called_handler,
    )


def build_weather_lookup(draft: IntentDraft) -> list[StepBlueprint]:
    return [StepBlueprint(tool="weather", action="lookup")]


def test_deterministic_pipeline_reaches_ready(
    planning_service: PlanningService,
    deterministic_matcher: DeterministicIntentMatcher,
    template_registry: PlanTemplateRegistry,
    tool_registry: ToolRegistry,
) -> None:
    register_weather_tool(tool_registry)
    deterministic_matcher.register(
        "weather", IntentDraft(type="weather.lookup", goal="check the weather")
    )
    template_registry.register("weather.lookup", build_weather_lookup)

    outcome = planning_service.create_and_plan(
        session_id="session-1", request_text="what's the weather"
    )

    assert isinstance(outcome, PlanningOutcome)
    assert outcome.task.state == TaskState.READY
    assert outcome.task.plan_id == outcome.plan.id
    assert outcome.intent.type == "weather.lookup"
    assert len(outcome.plan.steps) == 1
    assert outcome.plan.steps[0].tool == "weather"


def test_ambiguous_intent_blocks_task(
    planning_service: PlanningService, deterministic_matcher: DeterministicIntentMatcher
) -> None:
    deterministic_matcher.register(
        "maybe", IntentDraft(type="unclear", goal="unclear", confidence=0.1)
    )

    with pytest.raises(AmbiguousIntentError):
        planning_service.create_and_plan(session_id="session-1", request_text="maybe do it")


def test_no_deterministic_match_and_no_model_fails_planning(
    planning_service: PlanningService,
) -> None:
    with pytest.raises(MalformedModelOutputError):
        planning_service.create_and_plan(
            session_id="session-1", request_text="completely unrecognized request"
        )


def build_dangerous_step(draft: IntentDraft) -> list[StepBlueprint]:
    return [StepBlueprint(tool="unregistered.tool", action="do_thing")]


def test_plan_referencing_unregistered_tool_fails_planning(
    planning_service: PlanningService,
    deterministic_matcher: DeterministicIntentMatcher,
    template_registry: PlanTemplateRegistry,
) -> None:
    deterministic_matcher.register(
        "danger", IntentDraft(type="danger.action", goal="do something dangerous")
    )
    template_registry.register("danger.action", build_dangerous_step)

    with pytest.raises(PlanValidationError):
        planning_service.create_and_plan(session_id="session-1", request_text="danger please")


def test_model_fallback_builds_plan_when_no_template(
    orchestrator: Orchestrator,
    deterministic_matcher: DeterministicIntentMatcher,
    template_registry: PlanTemplateRegistry,
    tool_registry: ToolRegistry,
    intent_repository: SqliteIntentRepository,
    plan_repository: SqlitePlanRepository,
    audit_recorder: AuditRecorder,
    clock: Clock,
    id_generator: IdGenerator,
    scripted_model_provider: ScriptedModelProvider,
) -> None:
    register_weather_tool(tool_registry)

    # Intent parsing falls back to the model too (no deterministic match).
    scripted_model_provider.queue_response(
        ModelResponse(
            content="",
            structured_data={
                "type": "weather.lookup",
                "goal": "check the weather",
                "confidence": 0.95,
            },
        )
    )
    # No template registered for weather.lookup, so planning falls back
    # to the model as well.
    scripted_model_provider.queue_response(
        ModelResponse(
            content="",
            structured_data={"steps": [{"tool": "weather", "action": "lookup"}]},
        )
    )

    service = PlanningService(
        orchestrator=orchestrator,
        deterministic_matcher=deterministic_matcher,
        template_registry=template_registry,
        tool_registry=tool_registry,
        intent_repository=intent_repository,
        plan_repository=plan_repository,
        audit=audit_recorder,
        clock=clock,
        id_generator=id_generator,
        model_provider=scripted_model_provider,
    )

    outcome = service.create_and_plan(session_id="session-1", request_text="what's the weather")

    assert outcome.task.state == TaskState.READY
    assert outcome.plan.steps[0].tool == "weather"


def test_intent_is_persisted(
    planning_service: PlanningService,
    deterministic_matcher: DeterministicIntentMatcher,
    template_registry: PlanTemplateRegistry,
    tool_registry: ToolRegistry,
    intent_repository: SqliteIntentRepository,
) -> None:
    register_weather_tool(tool_registry)
    deterministic_matcher.register(
        "weather", IntentDraft(type="weather.lookup", goal="check the weather")
    )
    template_registry.register("weather.lookup", build_weather_lookup)

    outcome = planning_service.create_and_plan(
        session_id="session-1", request_text="what's the weather"
    )

    stored = intent_repository.get_by_task(outcome.task.id)
    assert stored is not None
    assert stored.type == "weather.lookup"


def test_ambiguous_intent_is_audited(
    planning_service: PlanningService,
    deterministic_matcher: DeterministicIntentMatcher,
    conn: sqlite3.Connection,
) -> None:
    deterministic_matcher.register(
        "maybe", IntentDraft(type="unclear", goal="unclear", confidence=0.1)
    )

    with pytest.raises(AmbiguousIntentError):
        planning_service.create_and_plan(session_id="session-1", request_text="maybe do it")

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE event_type = ?", ("understanding.ambiguous",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "blocked"