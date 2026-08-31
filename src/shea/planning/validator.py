from __future__ import annotations

from shea.contracts.models import Plan
from shea.tools.registry import ToolNotFoundError, ToolRegistry

from .exceptions import PlanValidationError


def validate_plan(plan: Plan, tool_registry: ToolRegistry) -> None:
    """Structural validation only: non-empty, every step has a tool, and
    every referenced tool is actually registered. Deliberately does NOT
    check capabilities or risk — that is DecisionService's job, downstream
    and separate, so this function stays a pure structural gate rather
    than duplicating authorization logic in two places.
    """
    if not plan.steps:
        raise PlanValidationError(plan.id, "plan has no steps")

    for step in plan.steps:
        if not step.tool:
            raise PlanValidationError(plan.id, f"step {step.id!r} has no tool")
        try:
            tool_registry.get_declaration(step.tool)
        except ToolNotFoundError as exc:
            raise PlanValidationError(
                plan.id, f"step {step.id!r} references unknown tool {step.tool!r}"
            ) from exc