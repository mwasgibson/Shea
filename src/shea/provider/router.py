from __future__ import annotations

from .health import ProviderHealthState
from .profile import ProviderProfile, ProviderTrustLevel
from .requirements import RoutingRequirements


class ProviderRouter:
    """Research doc Section 8.5's routing constraint order, applied as
    hard filters rather than weighted scoring — "Routing should start
    with hard constraints, not performance." Ranking among what remains
    is health-first (HEALTHY before DEGRADED; UNAVAILABLE is already
    excluded), matching Section 8.7's priority list without implementing
    every tier (reliability/latency/cost ranking is a documented
    simplification — see ProviderRoutingService).

    Pure: takes profiles and their current health, returns eligible
    profiles ranked best-first. Does not call `generate()`, does not
    know about ModelProvider instances, and does not mutate anything —
    consistent with every other pure engine in this codebase
    (PolicyEngine, RiskEngine, SecurityGate).
    """

    def eligible(
        self,
        providers: list[tuple[ProviderProfile, ProviderHealthState]],
        requirements: RoutingRequirements,
    ) -> list[ProviderProfile]:
        candidates: list[ProviderProfile] = []

        for profile, health in providers:
            if profile.trust_level is ProviderTrustLevel.UNTRUSTED:
                continue  # non-negotiable, Section 8.6
            if (
                requirements.require_local_only
                and profile.trust_level is not ProviderTrustLevel.LOCAL
            ):
                continue  # no privacy downgrade, Section 8.11
            if not requirements.required_capabilities <= profile.capabilities:
                continue  # no capability downgrade, Section 8.13
            if profile.context_limit < requirements.context_size_estimate:
                continue  # context compatibility, Section 8.12
            if health is ProviderHealthState.UNAVAILABLE:
                continue

            candidates.append(profile)

        health_by_id = {profile.provider_id: health for profile, health in providers}

        def _rank_key(profile: ProviderProfile) -> int:
            return 0 if health_by_id[profile.provider_id] is ProviderHealthState.HEALTHY else 1

        candidates.sort(key=_rank_key)
        return candidates