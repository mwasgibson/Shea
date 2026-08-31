from __future__ import annotations

from typing import Protocol

from shea.contracts.models import ModelResponse


class ModelProvider(Protocol):
    """Technical doc Section 8.5's provider-neutral model interface.

    `stream()` from the doc's full contract is deliberately not part of
    this Protocol yet — nothing in this codebase needs incremental output
    until the voice/streaming phase exists, and adding it speculatively
    now would mean guessing at an interface with no caller to validate it
    against.
    """

    def generate(self, prompt: str) -> ModelResponse: ...

    def health(self) -> bool: ...

    def capabilities(self) -> frozenset[str]: ...