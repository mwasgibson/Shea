from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from shea.understanding.deterministic import IntentDraft


@dataclass(frozen=True)
class StepBlueprint:
    """An unpersisted PlanStep — no id, no plan_id, no order, since those
    are assigned by whatever assembles the final Plan. Mirrors the
    "pure engine returns a Result, integration layer assigns identity"
    pattern used throughout (RiskAssessmentResult, IntentDraft, etc.).
    """

    tool: str
    action: str
    arguments: dict[str, Any] = field(default_factory=dict[str, Any])
    description: str = ""


BlueprintBuilder = Callable[[IntentDraft], list[StepBlueprint]]


class PlanTemplateRegistry:
    """Research doc Section 6.2's deterministic side applied to planning:
    a known intent type maps to a fixed, predictable sequence of steps.
    Intent types with no registered template fall through to the model
    fallback path in PlanningService — this registry has no fallback
    logic of its own, matching ToolRegistry and DeterministicIntentMatcher's
    "store rules, decide nothing" shape.
    """

    def __init__(self) -> None:
        self._templates: dict[str, BlueprintBuilder] = {}

    def register(self, intent_type: str, builder: BlueprintBuilder) -> None:
        self._templates[intent_type] = builder

    def build(self, intent_type: str, draft: IntentDraft) -> list[StepBlueprint] | None:
        builder = self._templates.get(intent_type)
        if builder is None:
            return None
        return builder(draft)