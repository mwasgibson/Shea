from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from shea.contracts.enums import PolicyVerdict
from shea.decision.policy import PolicyEngine

capability_pool = st.sampled_from(
    [
        "filesystem.read",
        "filesystem.write",
        "process.execute",
        "network.connect",
        "network.listen",
        "system.configure",
        "credential.access",
        "weather.lookup",
    ]
)

capability_sets = st.frozensets(capability_pool, min_size=0, max_size=5)


@given(
    capabilities=capability_sets,
    deny_set=st.frozensets(capability_pool, min_size=1, max_size=3),
)
def test_denied_verdict_is_never_downgraded_by_authorization_required_overlap(
    capabilities: frozenset[str], deny_set: frozenset[str]
) -> None:
    """Research doc Section 15.12's property, stated directly on the
    engine: whenever a requested capability set intersects the deny list,
    the verdict must be DENIED — never ALLOWED, never
    REQUIRES_AUTHORIZATION — no matter what else is also true about the
    request. There is no argument to `evaluate()` that changes this.
    """
    engine = PolicyEngine(
        deny_capabilities=deny_set,
        authorization_required_capabilities=capability_pool_as_frozenset(),
    )

    if capabilities & deny_set:
        assert engine.evaluate(capabilities) == PolicyVerdict.DENIED


@given(capabilities=capability_sets)
def test_verdict_is_always_one_of_three_values(capabilities: frozenset[str]) -> None:
    engine = PolicyEngine()
    verdict = engine.evaluate(capabilities)
    assert verdict in (
        PolicyVerdict.ALLOWED,
        PolicyVerdict.REQUIRES_AUTHORIZATION,
        PolicyVerdict.DENIED,
    )


@given(capabilities=capability_sets)
def test_disjoint_from_both_lists_is_always_allowed(capabilities: frozenset[str]) -> None:
    engine = PolicyEngine(
        deny_capabilities=frozenset({"credential.access"}),
        authorization_required_capabilities=frozenset({"network.connect"}),
    )
    if not (capabilities & engine.deny_capabilities) and not (
        capabilities & engine.authorization_required_capabilities
    ):
        assert engine.evaluate(capabilities) == PolicyVerdict.ALLOWED


def capability_pool_as_frozenset() -> frozenset[str]:
    return frozenset(
        {
            "filesystem.read",
            "filesystem.write",
            "process.execute",
            "network.connect",
            "network.listen",
            "system.configure",
            "credential.access",
            "weather.lookup",
        }
    )
