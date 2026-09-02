from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProviderTrustLevel(StrEnum):
    """Research doc Section 8.6's provider classes.

    UNTRUSTED is the non-negotiable tier: "Not eligible for normal
    routing. Routing: DENIED." — the same shape as PolicyEngine's
    deny_capabilities (Phase 2) and SecurityGate's SSRF blocking
    (Phase 6). ProviderRouter excludes UNTRUSTED providers unconditionally;
    there is no requirements field that overrides this.
    """

    LOCAL = "LOCAL"
    TRUSTED_REMOTE = "TRUSTED_REMOTE"
    UNTRUSTED = "UNTRUSTED"


@dataclass(frozen=True)
class ProviderProfile:
    """Research doc Section 8.3's Provider abstraction, trimmed to what
    routing decisions actually need: identity, trust, capabilities, and
    context limit. Execution itself happens through the ModelProvider
    port (generate/health/capabilities) — this profile is metadata used
    to decide *whether* to call a given provider, not how to call it.
    """

    provider_id: str
    model_id: str
    trust_level: ProviderTrustLevel
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset())
    context_limit: int = 8000