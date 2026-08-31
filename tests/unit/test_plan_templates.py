from __future__ import annotations

import pytest

from shea.contracts.models import Plan, PlanStep, ToolRequest, ToolResponse
from shea.planning.capabilities import capabilities_for_plan
from shea.planning.exceptions import PlanValidationError
from shea.planning.templates import PlanTemplateRegistry, StepBlueprint
from shea.planning.validator import validate_plan
from shea.tools.registry import ToolDeclaration, ToolRegistry
from shea.understanding.deterministic import IntentDraft


def _noop_handler(request: ToolRequest) -> ToolResponse:
    return ToolResponse(success=True)


def test_registry_returns_none_for_unregistered_type() -> None:
    registry = PlanTemplateRegistry()
    assert registry.build("unknown.type", IntentDraft(type="unknown.type", goal="x")) is None


def test_registry_builds_from_registered_template() -> None:
    registry = PlanTemplateRegistry()

    def build_weather_lookup(draft: IntentDraft) -> list[StepBlueprint]:
        return [StepBlueprint(tool="weather", action="lookup", arguments=draft.parameters)]

    registry.register("weather.lookup", build_weather_lookup)

    blueprints = registry.build(
        "weather.lookup", IntentDraft(type="weather.lookup", goal="x", parameters={"city": "nyc"})
    )

    assert blueprints is not None
    assert len(blueprints) == 1
    assert blueprints[0].tool == "weather"
    assert blueprints[0].arguments == {"city": "nyc"}


def make_plan(steps: list[PlanStep]) -> Plan:
    return Plan(id="plan-1", task_id="task-1", objective="do something", steps=steps)


def test_validate_plan_rejects_empty_steps() -> None:
    plan = make_plan([])
    registry = ToolRegistry()

    with pytest.raises(PlanValidationError):
        validate_plan(plan, registry)


def test_validate_plan_rejects_step_with_no_tool() -> None:
    plan = make_plan(
        [PlanStep(id="step-1", plan_id="plan-1", order=0, description="x", tool=None)]
    )
    registry = ToolRegistry()

    with pytest.raises(PlanValidationError):
        validate_plan(plan, registry)


def test_validate_plan_rejects_unregistered_tool() -> None:
    plan = make_plan(
        [PlanStep(id="step-1", plan_id="plan-1", order=0, description="x", tool="ghost.tool")]
    )
    registry = ToolRegistry()

    with pytest.raises(PlanValidationError):
        validate_plan(plan, registry)


def test_validate_plan_accepts_well_formed_plan() -> None:
    registry = ToolRegistry()
    registry.register(ToolDeclaration(name="echo", capabilities=frozenset()), _noop_handler)
    plan = make_plan(
        [PlanStep(id="step-1", plan_id="plan-1", order=0, description="x", tool="echo")]
    )

    validate_plan(plan, registry)  # must not raise


def test_capabilities_for_plan_unions_across_steps() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDeclaration(name="a", capabilities=frozenset({"network.connect"})), _noop_handler
    )
    registry.register(
        ToolDeclaration(name="b", capabilities=frozenset({"filesystem.write"})), _noop_handler
    )
    plan = make_plan(
        [
            PlanStep(id="step-1", plan_id="plan-1", order=0, description="x", tool="a"),
            PlanStep(id="step-2", plan_id="plan-1", order=1, description="y", tool="b"),
        ]
    )

    capabilities = capabilities_for_plan(plan, registry)

    assert capabilities == frozenset({"network.connect", "filesystem.write"})


def test_capabilities_for_plan_empty_when_no_steps_have_tools() -> None:
    registry = ToolRegistry()
    plan = make_plan([])

    assert capabilities_for_plan(plan, registry) == frozenset()