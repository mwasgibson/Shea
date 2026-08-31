from __future__ import annotations

import pytest

from shea.contracts.models import ModelResponse
from shea.model.exceptions import MalformedModelOutputError
from shea.model.scripted import ScriptedModelProvider
from shea.understanding.deterministic import DeterministicIntentMatcher, IntentDraft
from shea.understanding.exceptions import AmbiguousIntentError
from shea.understanding.parser import IntentParser


def test_matcher_matches_registered_trigger() -> None:
    matcher = DeterministicIntentMatcher()
    matcher.register("open firefox", IntentDraft(type="application.launch", goal="open firefox"))

    result = matcher.match("please Open Firefox for me")

    assert result is not None
    assert result.type == "application.launch"


def test_matcher_is_case_insensitive() -> None:
    matcher = DeterministicIntentMatcher()
    matcher.register("open firefox", IntentDraft(type="application.launch", goal="open firefox"))

    assert matcher.match("OPEN FIREFOX") is not None


def test_matcher_returns_none_for_no_match() -> None:
    matcher = DeterministicIntentMatcher()
    matcher.register("open firefox", IntentDraft(type="application.launch", goal="open firefox"))

    assert matcher.match("what's the weather") is None


def test_matcher_returns_first_registered_match() -> None:
    matcher = DeterministicIntentMatcher()
    matcher.register("open", IntentDraft(type="a", goal="a"))
    matcher.register("open firefox", IntentDraft(type="b", goal="b"))

    result = matcher.match("open firefox")

    assert result is not None
    assert result.type == "a"


def test_parser_prefers_deterministic_match_over_model() -> None:
    matcher = DeterministicIntentMatcher()
    matcher.register("open firefox", IntentDraft(type="application.launch", goal="open firefox"))
    model = ScriptedModelProvider()  # queue left empty; must never be called

    parser = IntentParser(matcher, model)
    draft = parser.parse("open firefox")

    assert draft.type == "application.launch"
    assert draft.source == "deterministic"


def test_parser_falls_back_to_model_on_no_match() -> None:
    matcher = DeterministicIntentMatcher()
    model = ScriptedModelProvider()
    model.queue_response(
        ModelResponse(
            content="",
            structured_data={
                "type": "weather.lookup",
                "goal": "check the weather",
                "confidence": 0.9,
                "parameters": {"location": "here"},
            },
        )
    )

    parser = IntentParser(matcher, model)
    draft = parser.parse("what's the weather like")

    assert draft.type == "weather.lookup"
    assert draft.confidence == 0.9
    assert draft.source == "model"
    assert draft.parameters == {"location": "here"}


def test_parser_raises_when_no_match_and_no_model_configured() -> None:
    matcher = DeterministicIntentMatcher()
    parser = IntentParser(matcher, model_provider=None)

    with pytest.raises(MalformedModelOutputError):
        parser.parse("something unrecognized")


def test_parser_raises_on_missing_required_field() -> None:
    matcher = DeterministicIntentMatcher()
    model = ScriptedModelProvider()
    model.queue_response(ModelResponse(content="", structured_data={"goal": "no type field"}))

    parser = IntentParser(matcher, model)

    with pytest.raises(MalformedModelOutputError):
        parser.parse("anything")


def test_parser_raises_on_invalid_confidence_type() -> None:
    matcher = DeterministicIntentMatcher()
    model = ScriptedModelProvider()
    model.queue_response(
        ModelResponse(
            content="",
            structured_data={"type": "x", "goal": "y", "confidence": "high"},
        )
    )

    parser = IntentParser(matcher, model)

    with pytest.raises(MalformedModelOutputError):
        parser.parse("anything")


def test_parser_raises_on_out_of_range_confidence() -> None:
    matcher = DeterministicIntentMatcher()
    model = ScriptedModelProvider()
    model.queue_response(
        ModelResponse(content="", structured_data={"type": "x", "goal": "y", "confidence": 1.5})
    )

    parser = IntentParser(matcher, model)

    with pytest.raises(MalformedModelOutputError):
        parser.parse("anything")


def test_parser_raises_on_non_dict_structured_data() -> None:
    matcher = DeterministicIntentMatcher()
    model = ScriptedModelProvider()
    model.queue_response(ModelResponse(content="just prose", structured_data=None))

    parser = IntentParser(matcher, model)

    with pytest.raises(MalformedModelOutputError):
        parser.parse("anything")


def test_parser_raises_ambiguous_below_threshold() -> None:
    matcher = DeterministicIntentMatcher()
    matcher.register(
        "maybe do something",
        IntentDraft(type="unclear", goal="unclear", confidence=0.2),
    )

    parser = IntentParser(matcher, confidence_threshold=0.5)

    with pytest.raises(AmbiguousIntentError) as exc_info:
        parser.parse("maybe do something")

    assert exc_info.value.draft.confidence == 0.2
    assert exc_info.value.threshold == 0.5


def test_parser_accepts_confidence_exactly_at_threshold() -> None:
    matcher = DeterministicIntentMatcher()
    matcher.register("borderline", IntentDraft(type="x", goal="y", confidence=0.5))

    parser = IntentParser(matcher, confidence_threshold=0.5)
    draft = parser.parse("borderline")

    assert draft.confidence == 0.5