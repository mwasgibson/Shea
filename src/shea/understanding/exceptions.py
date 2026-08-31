from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .deterministic import IntentDraft


class AmbiguousIntentError(Exception):
    """Raised when a parsed intent's confidence falls below the
    configured threshold — research doc Section 6.6: "When should Shea
    ask for clarification?" Carries the low-confidence draft so a caller
    can present it to the user ("I think you mean X. Confirm?") rather
    than needing a second parse just to explain what was ambiguous.
    """

    def __init__(self, draft: IntentDraft, threshold: float) -> None:
        self.draft = draft
        self.threshold = threshold
        super().__init__(
            f"Intent confidence {draft.confidence} is below the required "
            f"threshold {threshold} (goal={draft.goal!r})"
        )