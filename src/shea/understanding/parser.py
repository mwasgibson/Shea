from __future__ import annotations

from typing import Any, cast

from shea.model.exceptions import MalformedModelOutputError
from shea.ports.model_provider import ModelProvider

from .deterministic import DeterministicIntentMatcher, IntentDraft
from .exceptions import AmbiguousIntentError

DEFAULT_CONFIDENCE_THRESHOLD = 0.5


def _build_intent_prompt(text: str) -> str:
    return (
        "Extract a structured intent from the following user request. "
        "Respond with a JSON object containing: type, goal, parameters, confidence.\n\n"
        f"User request: {text}"
    )


def _draft_from_model_data(data: object, source: str) -> IntentDraft:
    if not isinstance(data, dict):
        raise MalformedModelOutputError("model response had no structured_data object")

    payload = cast(dict[str, Any], data)
    
    try:
        intent_type = str(payload["type"])
        goal = str(payload["goal"])
    except KeyError as exc:
        raise MalformedModelOutputError(f"model response missing required field {exc}") from exc

    confidence = payload.get("confidence", 0.0)
    if not isinstance(confidence, int | float) or not (0.0 <= confidence <= 1.0):
        raise MalformedModelOutputError(
            f"model response confidence {confidence!r} is not a number in [0, 1]"
        )

    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict):
        raise MalformedModelOutputError("model response 'parameters' must be an object")

    typed_parameters = cast(dict[str, Any], parameters)
    
    return IntentDraft(
        type=intent_type,
        goal=goal,
        parameters=typed_parameters,
        confidence=float(confidence),
        source=source,
    )


class IntentParser:
    """Technical doc Component: Understanding Engine ("Converts input
    into structured intent"), implementing research doc Section 6.2's
    hybrid: deterministic matching first, model fallback second. The
    model is never given unrestricted authority to "decide what to do" —
    it performs reading comprehension over the request and returns
    structured data, which is validated exactly as strictly as any other
    untrusted input before becoming an IntentDraft.
    """

    def __init__(
        self,
        deterministic_matcher: DeterministicIntentMatcher,
        model_provider: ModelProvider | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._matcher = deterministic_matcher
        self._model = model_provider
        self._threshold = confidence_threshold

    def parse(self, text: str) -> IntentDraft:
        draft = self._matcher.match(text)
        if draft is None:
            draft = self._parse_with_model(text)

        if draft.confidence < self._threshold:
            raise AmbiguousIntentError(draft, self._threshold)

        return draft

    def _parse_with_model(self, text: str) -> IntentDraft:
        if self._model is None:
            raise MalformedModelOutputError(
                "no deterministic match and no model provider configured"
            )
        response = self._model.generate(_build_intent_prompt(text))
        return _draft_from_model_data(response.structured_data, source="model")