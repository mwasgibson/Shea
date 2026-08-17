from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from shea.contracts.models import Task


@dataclass(frozen=True)
class CompensationOutcome:
    restored: bool
    method: str
    explanation: str


Compensator = Callable[[Task], CompensationOutcome]


def default_compensator(task: Task) -> CompensationOutcome:
    """Fallback used when no real compensation action is configured.

    Technical doc Constraint 5: "Rollback must never be claimed successful
    without verification." Phase 4 has no real external side effects to
    roll back, so the only honest default is `restored=False` — reporting
    that nothing was confirmed restored. This is deliberately NOT an
    optimistic default; a caller with an actual compensating action
    (undo a filesystem write, cancel a request, etc.) must supply its own
    Compensator that performs the action and independently confirms it
    worked before returning `restored=True`.
    """
    return CompensationOutcome(
        restored=False,
        method="none",
        explanation="No compensator configured for this task; nothing was restored.",
    )