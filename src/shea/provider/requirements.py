from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoutingRequirements:
    """Research doc Section 8.5's routing constraints, trimmed to the
    three that ProviderRouter can check purely from a ProviderProfile:
    required capabilities, minimum context headroom, and whether the
    request's data is permitted to leave the machine at all.

    `require_local_only=True` is the concrete form of Section 8.11: "If
    Provider A (LOCAL) fails, the router cannot automatically do
    Provider B (REMOTE) unless the context is permitted to leave the
    machine." When set, no TRUSTED_REMOTE provider is ever eligible —
    not as a first choice, not as a failover.
    """

    required_capabilities: frozenset[str] = field(default_factory=lambda: frozenset())
    context_size_estimate: int = 0
    require_local_only: bool = False