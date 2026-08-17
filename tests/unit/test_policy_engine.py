from __future__ import annotations

from shea.contracts.enums import PolicyVerdict
from shea.decision.policy import PolicyEngine


def test_no_flagged_capabilities_is_allowed() -> None:
    engine = PolicyEngine(
        deny_capabilities=frozenset(),
        authorization_required_capabilities=frozenset({"network.connect"}),
    )
    assert engine.evaluate(frozenset({"weather.lookup"})) == PolicyVerdict.ALLOWED


def test_authorization_required_capability_yields_requires_authorization() -> None:
    engine = PolicyEngine(
        deny_capabilities=frozenset(),
        authorization_required_capabilities=frozenset({"network.connect"}),
    )
    assert (
        engine.evaluate(frozenset({"network.connect"}))
        == PolicyVerdict.REQUIRES_AUTHORIZATION
    )


def test_denied_capability_always_wins_over_authorization_required() -> None:
    """A capability set that hits both the deny list and the
    authorization-required list must be DENIED, never
    REQUIRES_AUTHORIZATION — deny is the non-negotiable tier and must
    take precedence whenever both apply.
    """
    engine = PolicyEngine(
        deny_capabilities=frozenset({"credential.access"}),
        authorization_required_capabilities=frozenset({"credential.access", "network.connect"}),
    )
    verdict = engine.evaluate(frozenset({"credential.access", "network.connect"}))
    assert verdict == PolicyVerdict.DENIED


def test_empty_capabilities_is_allowed() -> None:
    engine = PolicyEngine()
    assert engine.evaluate(frozenset()) == PolicyVerdict.ALLOWED


def test_default_authorization_required_set_covers_doc_examples() -> None:
    engine = PolicyEngine()
    for capability in (
        "filesystem.write",
        "process.execute",
        "network.connect",
        "network.listen",
        "system.configure",
        "credential.access",
    ):
        assert engine.evaluate(frozenset({capability})) == PolicyVerdict.REQUIRES_AUTHORIZATION


def test_default_deny_set_is_empty_by_default() -> None:
    """No capability is denied out of the box — deny rules are a
    deployment decision (later Security phase), not baked into the engine.
    """
    engine = PolicyEngine()
    assert engine.deny_capabilities == frozenset()
