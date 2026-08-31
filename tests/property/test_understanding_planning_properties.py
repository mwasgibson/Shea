from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from shea.contracts.models import ModelResponse
from shea.model.exceptions import MalformedModelOutputError
from shea.model.scripted import ScriptedModelProvider
from shea.understanding.deterministic import DeterministicIntentMatcher
from shea.understanding.exceptions import AmbiguousIntentError
from shea.understanding.parser import IntentParser


@given(
    confidence=st.floats(min_value=0.0, max_value=1.0),
    threshold=st.floats(min_value=0.0, max_value=1.0),
)
def test_ambiguous_iff_confidence_below_threshold(confidence: float, threshold: float) -> None:
    """The defining property of the confidence gate: across every
    combination of confidence and threshold, parsing raises
    AmbiguousIntentError exactly when confidence < threshold — never
    "close enough," never inconsistently.
    """
    matcher = DeterministicIntentMatcher()
    model = ScriptedModelProvider()
    model.queue_response(
        ModelResponse(
            content="",
            structured_data={"type": "x", "goal": "y", "confidence": confidence},
        )
    )
    parser = IntentParser(matcher, model, confidence_threshold=threshold)

    if confidence < threshold:
        try:
            parser.parse("anything")
        except AmbiguousIntentError:
            pass
        else:
            raise AssertionError("expected AmbiguousIntentError")
    else:
        draft = parser.parse("anything")
        assert draft.confidence == confidence


@given(
    missing_field=st.sampled_from(["type", "goal"]),
    other_value=st.text(min_size=1, max_size=10),
)
def test_missing_required_field_always_raises(missing_field: str, other_value: str) -> None:
    """Whichever required field (type or goal) is missing from the
    model's structured output, parsing must always raise
    MalformedModelOutputError — never substitute a default, never
    silently accept partial data.
    """
    data: dict[str, Any] = {"type": other_value, "goal": other_value, "confidence": 1.0}
    del data[missing_field]

    matcher = DeterministicIntentMatcher()
    model = ScriptedModelProvider()
    model.queue_response(ModelResponse(content="", structured_data=data))
    parser = IntentParser(matcher, model)

    try:
        parser.parse("anything")
    except MalformedModelOutputError:
        pass
    else:
        raise AssertionError("expected MalformedModelOutputError")