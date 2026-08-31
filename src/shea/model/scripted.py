from __future__ import annotations

from shea.contracts.models import ModelResponse

from .exceptions import ModelUnavailableError

DEFAULT_CAPABILITIES: frozenset[str] = frozenset({"structured_output"})


class ScriptedModelProvider:
    """A deterministic ModelProvider implementation that returns
    pre-queued responses in order — research doc Section 15.5's "Fake
    Providers" concept (Success, Timeout, Malformed response, ...),
    implemented as a real, reusable ModelProvider rather than test-only
    glue, since Understanding and Planning need something concrete to
    exercise the model fallback path against.

    This is NOT a production model integration. No real LLM API call
    happens here — wiring up an actual provider (OpenAI, Anthropic, a
    local model) is the Provider Routing phase's job, per research doc
    Section 8. Until then, this is what stands in the `model_provider`
    slot: for tests, for dry runs, or for a deployment that wants
    deterministic canned behavior for specific known inputs.
    """

    def __init__(
        self, name: str = "scripted", capabilities: frozenset[str] = DEFAULT_CAPABILITIES
    ) -> None:
        self._name = name
        self._capabilities = capabilities
        self._queue: list[ModelResponse] = []
        self._healthy = True

    def queue_response(self, response: ModelResponse) -> None:
        self._queue.append(response)

    def set_healthy(self, healthy: bool) -> None:
        self._healthy = healthy

    def generate(self, prompt: str) -> ModelResponse:
        if not self._queue:
            raise ModelUnavailableError(self._name)
        return self._queue.pop(0)

    def health(self) -> bool:
        return self._healthy

    def capabilities(self) -> frozenset[str]:
        return self._capabilities