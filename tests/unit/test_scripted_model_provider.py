from __future__ import annotations

import pytest

from shea.contracts.models import ModelResponse
from shea.model.exceptions import ModelUnavailableError
from shea.model.scripted import ScriptedModelProvider


def test_returns_queued_responses_in_order() -> None:
    provider = ScriptedModelProvider()
    provider.queue_response(ModelResponse(content="first"))
    provider.queue_response(ModelResponse(content="second"))

    assert provider.generate("prompt").content == "first"
    assert provider.generate("prompt").content == "second"


def test_raises_when_queue_is_exhausted() -> None:
    provider = ScriptedModelProvider(name="test-provider")

    with pytest.raises(ModelUnavailableError) as exc_info:
        provider.generate("prompt")

    assert exc_info.value.provider_name == "test-provider"


def test_health_defaults_to_true_and_is_settable() -> None:
    provider = ScriptedModelProvider()
    assert provider.health() is True

    provider.set_healthy(False)
    assert provider.health() is False


def test_capabilities_default_to_structured_output() -> None:
    provider = ScriptedModelProvider()
    assert "structured_output" in provider.capabilities()


def test_capabilities_are_configurable() -> None:
    provider = ScriptedModelProvider(capabilities=frozenset({"tool_calling"}))
    assert provider.capabilities() == frozenset({"tool_calling"})