from __future__ import annotations

from shea.provider.health import ProviderHealthState
from shea.provider.profile import ProviderProfile, ProviderTrustLevel
from shea.provider.requirements import RoutingRequirements
from shea.provider.router import ProviderRouter


def local_profile(provider_id: str = "local-1", **overrides: object) -> ProviderProfile:
    defaults: dict[str, object] = dict(
        provider_id=provider_id,
        model_id="local-model",
        trust_level=ProviderTrustLevel.LOCAL,
        capabilities=frozenset({"structured_output"}),
        context_limit=8000,
    )
    defaults.update(overrides)
    return ProviderProfile(**defaults)  # type: ignore[arg-type]


def test_untrusted_provider_is_never_eligible() -> None:
    router = ProviderRouter()
    profile = local_profile(trust_level=ProviderTrustLevel.UNTRUSTED)

    result = router.eligible([(profile, ProviderHealthState.HEALTHY)], RoutingRequirements())

    assert result == []


def test_require_local_only_excludes_trusted_remote() -> None:
    router = ProviderRouter()
    remote = local_profile(trust_level=ProviderTrustLevel.TRUSTED_REMOTE)

    result = router.eligible(
        [(remote, ProviderHealthState.HEALTHY)],
        RoutingRequirements(require_local_only=True),
    )

    assert result == []


def test_require_local_only_permits_local_provider() -> None:
    router = ProviderRouter()
    local = local_profile(trust_level=ProviderTrustLevel.LOCAL)

    result = router.eligible(
        [(local, ProviderHealthState.HEALTHY)],
        RoutingRequirements(require_local_only=True),
    )

    assert result == [local]


def test_missing_required_capability_excludes_provider() -> None:
    router = ProviderRouter()
    profile = local_profile(capabilities=frozenset({"structured_output"}))

    result = router.eligible(
        [(profile, ProviderHealthState.HEALTHY)],
        RoutingRequirements(required_capabilities=frozenset({"tool_calling"})),
    )

    assert result == []


def test_context_limit_too_small_excludes_provider() -> None:
    router = ProviderRouter()
    profile = local_profile(context_limit=1000)

    result = router.eligible(
        [(profile, ProviderHealthState.HEALTHY)],
        RoutingRequirements(context_size_estimate=5000),
    )

    assert result == []


def test_unavailable_provider_is_excluded() -> None:
    router = ProviderRouter()
    profile = local_profile()

    result = router.eligible(
        [(profile, ProviderHealthState.UNAVAILABLE)], RoutingRequirements()
    )

    assert result == []


def test_degraded_provider_is_still_eligible_but_ranked_after_healthy() -> None:
    router = ProviderRouter()
    degraded = local_profile(provider_id="degraded-1")
    healthy = local_profile(provider_id="healthy-1")

    result = router.eligible(
        [
            (degraded, ProviderHealthState.DEGRADED),
            (healthy, ProviderHealthState.HEALTHY),
        ],
        RoutingRequirements(),
    )

    assert [p.provider_id for p in result] == ["healthy-1", "degraded-1"]


def test_multiple_eligible_providers_all_returned() -> None:
    router = ProviderRouter()
    a = local_profile(provider_id="a")
    b = local_profile(provider_id="b")

    result = router.eligible(
        [(a, ProviderHealthState.HEALTHY), (b, ProviderHealthState.HEALTHY)],
        RoutingRequirements(),
    )

    assert {p.provider_id for p in result} == {"a", "b"}