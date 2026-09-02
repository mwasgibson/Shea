from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from shea.provider.health import ProviderHealthState
from shea.provider.profile import ProviderProfile, ProviderTrustLevel
from shea.provider.requirements import RoutingRequirements
from shea.provider.router import ProviderRouter

trust_levels = st.sampled_from(list(ProviderTrustLevel))
health_states = st.sampled_from(list(ProviderHealthState))
capability_pool = st.sampled_from(["structured_output", "tool_calling", "vision", "streaming"])


@given(
    trust_level=trust_levels,
    health=health_states,
    capabilities=st.frozensets(capability_pool, max_size=3),
)
def test_untrusted_is_never_eligible_regardless_of_other_factors(
    trust_level: ProviderTrustLevel, health: ProviderHealthState, capabilities: frozenset[str]
) -> None:
    """Mirrors PolicyEngine's DENIED-never-downgraded property (Phase 2)
    and SecurityGate's SSRF property (Phase 6): whatever else is true
    about a provider, UNTRUSTED trust level excludes it from every
    routing decision, with no combination of health/capabilities able to
    override that.
    """
    profile = ProviderProfile(
        provider_id="p1",
        model_id="m1",
        trust_level=trust_level,
        capabilities=capabilities,
        context_limit=8000,
    )
    router = ProviderRouter()

    result = router.eligible([(profile, health)], RoutingRequirements())

    if trust_level is ProviderTrustLevel.UNTRUSTED:
        assert result == []


@given(health=health_states)
def test_unavailable_health_always_excludes_regardless_of_trust(
    health: ProviderHealthState,
) -> None:
    profile = ProviderProfile(
        provider_id="p1",
        model_id="m1",
        trust_level=ProviderTrustLevel.LOCAL,
        capabilities=frozenset(),
        context_limit=8000,
    )
    router = ProviderRouter()

    result = router.eligible([(profile, health)], RoutingRequirements())

    if health is ProviderHealthState.UNAVAILABLE:
        assert result == []
    else:
        assert result == [profile]


@given(
    required=st.frozensets(capability_pool, max_size=3),
    available=st.frozensets(capability_pool, max_size=3),
)
def test_eligible_iff_required_capabilities_are_subset(
    required: frozenset[str], available: frozenset[str]
) -> None:
    profile = ProviderProfile(
        provider_id="p1",
        model_id="m1",
        trust_level=ProviderTrustLevel.LOCAL,
        capabilities=available,
        context_limit=8000,
    )
    router = ProviderRouter()

    result = router.eligible(
        [(profile, ProviderHealthState.HEALTHY)],
        RoutingRequirements(required_capabilities=required),
    )

    if required <= available:
        assert result == [profile]
    else:
        assert result == []