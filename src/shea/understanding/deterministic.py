from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IntentDraft:
    """The output of intent parsing before it becomes a persisted Intent
    — mirrors RiskAssessmentResult in shea.decision.risk: no id, no
    task_id, nothing that requires a caller-supplied identity. The
    integration layer (PlanningService) is responsible for turning this
    into a real Intent.
    """

    type: str
    goal: str
    parameters: dict[str, Any] = field(default_factory=dict[str, Any])
    confidence: float = 1.0
    source: str = "deterministic"


class DeterministicIntentMatcher:
    """Research doc Section 6.2: "Deterministic schemas: Input -> Parser
    -> Structured command. Advantages: Predictable, testable, fast,
    easier to secure." This is intentionally the simplest possible
    matcher — ordered, case-insensitive substring triggers — not a real
    NLU system. A production deployment with richer slot-filling needs
    would extend or replace this, not the IntentParser that wraps it.
    """

    def __init__(self) -> None:
        self._rules: list[tuple[str, IntentDraft]] = []

    def register(self, trigger: str, draft: IntentDraft) -> None:
        self._rules.append((trigger.lower(), draft))

    def match(self, text: str) -> IntentDraft | None:
        normalized = text.strip().lower()
        for trigger, draft in self._rules:
            if trigger in normalized:
                return draft
        return None