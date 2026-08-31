from __future__ import annotations


class MalformedModelOutputError(Exception):
    """Raised whenever a ModelProvider's output cannot be used as
    structured input to Understanding or Planning — missing required
    fields, wrong types, or no structured_data at all. Functional
    requirement: "SHEA shall validate tool arguments before execution"
    extends naturally to model output — nothing downstream should ever
    see unvalidated model JSON.
    """


class ModelUnavailableError(Exception):
    """Raised by a ModelProvider implementation when it cannot produce a
    response at all (e.g. ScriptedModelProvider's queue is exhausted, or
    a real provider is down). Distinct from MalformedModelOutputError:
    this means no response came back, not that one came back malformed.
    """

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"Model provider {provider_name!r} is unavailable")