from __future__ import annotations

from shea.contracts.models import Plan
from shea.tools.registry import ToolRegistry


def capabilities_for_plan(plan: Plan, tool_registry: ToolRegistry) -> frozenset[str]:
    """The union of every step's declared tool capabilities — this is
    what DecisionService.evaluate_and_authorize() should be called with,
    closing the loop from "a plan wants to do things" to "here is exactly
    what needs to be authorized." Assumes `validate_plan` already ran, so
    every step's tool is known to be registered; call order matters.
    """
    capabilities: set[str] = set()
    for step in plan.steps:
        if step.tool:
            capabilities |= tool_registry.get_declaration(step.tool).capabilities
    return frozenset(capabilities)