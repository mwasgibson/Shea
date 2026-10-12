from __future__ import annotations

from pathlib import Path

import pytest

from shea.bootstrap import build_runtime
from shea.contracts.models import ModelResponse
from shea.model.exceptions import MalformedModelOutputError, ModelUnavailableError
from shea.model.scripted import ScriptedModelProvider
from shea.understanding.deterministic import DeterministicIntentMatcher
from shea.understanding.parser import IntentParser

UNPARSEABLE = ModelResponse(content="Sure! Happy to help with that.", structured_data=None)


def _classification(**extra: object) -> ModelResponse:
    data = {"type": "query", "goal": "chat", "confidence": 1.0, **extra}
    return ModelResponse(content="", structured_data=data)


def _parser(provider: ScriptedModelProvider) -> IntentParser:
    return IntentParser(DeterministicIntentMatcher(), provider)


def test_combined_call_carries_the_reply() -> None:
    provider = ScriptedModelProvider()
    provider.queue_response(_classification(reply="Hello!"))

    draft = _parser(provider).parse("hi")

    assert draft.reply == "Hello!"
    assert len(provider.calls) == 1
    assert '"reply"' in provider.calls[0]


def test_a_task_never_carries_a_pre_made_reply() -> None:
    provider = ScriptedModelProvider()
    provider.queue_response(
        ModelResponse(
            content="",
            structured_data={
                "type": "task",
                "goal": "delete it",
                "confidence": 1.0,
                "reply": "Done, I deleted it.",
            },
        )
    )

    draft = _parser(provider).parse("delete the file")

    assert draft.type == "task"
    assert draft.reply is None


def test_unparseable_combined_output_falls_back_to_the_classification_only_prompt() -> None:
    provider = ScriptedModelProvider()
    provider.queue_response(UNPARSEABLE)
    provider.queue_response(_classification())

    draft = _parser(provider).parse("hi")

    assert draft.type == "query"
    assert draft.reply is None  # answered by the dedicated call afterwards
    assert len(provider.calls) == 2
    assert '"reply"' in provider.calls[0]
    assert '"reply"' not in provider.calls[1]  # the short, reliable prompt


def test_both_prompts_unparseable_raises_after_exactly_two_calls() -> None:
    provider = ScriptedModelProvider()
    provider.queue_response(UNPARSEABLE)
    provider.queue_response(UNPARSEABLE)

    with pytest.raises(MalformedModelOutputError):
        _parser(provider).parse("hi")

    assert len(provider.calls) == 2


def test_a_provider_outage_is_not_retried() -> None:
    provider = ScriptedModelProvider()  # empty queue -> ModelUnavailableError

    with pytest.raises(ModelUnavailableError):
        _parser(provider).parse("hi")

    assert len(provider.calls) == 1


def test_full_turn_survives_a_model_that_cannot_do_the_combined_format(tmp_path: Path) -> None:
    """Worst realistic case end to end: combined output unusable, so
    classify-only, then the dedicated answer call. Three calls, and the
    user still gets their answer instead of a 'Critical failure'."""
    provider = ScriptedModelProvider()
    provider.queue_response(UNPARSEABLE)
    provider.queue_response(_classification())
    provider.queue_response(ModelResponse(content="Paris."))
    runtime = build_runtime(
        tmp_path / "shea.db", workspace=tmp_path / "ws", model_provider=provider
    )

    result = runtime.interaction_service.handle_text("capital of france?", run=True)

    assert result.error is None
    assert result.message == "Paris."
    assert len(provider.calls) == 3
    runtime.conn.close()
