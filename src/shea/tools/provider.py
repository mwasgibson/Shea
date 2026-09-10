from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from shea.tools.registry import ToolRegistry
from shea.verification.verifier import VerifierRegistry


class ToolProvider(Protocol):
    """Registers one or more tools into a registry.

    Providers never execute tools and never authorize them. They only
    attach declarations + handlers (and optional verifiers). Decision
    and ToolExecutor remain the only authority paths.
    """

    name: str

    def register(
        self,
        registry: ToolRegistry,
        *,
        verifier_registry: VerifierRegistry | None = None,
    ) -> None: ...


def load_tools(
    registry: ToolRegistry,
    providers: Sequence[ToolProvider],
    *,
    verifier_registry: VerifierRegistry | None = None,
) -> list[str]:
    """Register all providers into ``registry``.

    Returns the provider names that were loaded, in order.
    """
    loaded: list[str] = []
    for provider in providers:
        provider.register(registry, verifier_registry=verifier_registry)
        loaded.append(provider.name)
    return loaded