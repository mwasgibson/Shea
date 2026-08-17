from __future__ import annotations

from shea.contracts.enums import RiskLevel
from shea.decision.risk import RiskEngine, RiskFactors


def test_no_factors_is_safe() -> None:
    engine = RiskEngine()
    result = engine.assess(RiskFactors(capabilities=frozenset(), reversible=True))
    assert result.level == RiskLevel.SAFE
    assert result.factors == []


def test_one_factor_is_low() -> None:
    engine = RiskEngine()
    result = engine.assess(
        RiskFactors(capabilities=frozenset({"process.execute"}), reversible=True)
    )
    assert result.level == RiskLevel.LOW
    assert result.factors == ["Elevated privileges"]


def test_two_factors_is_medium() -> None:
    engine = RiskEngine()
    result = engine.assess(
        RiskFactors(
            capabilities=frozenset({"process.execute", "network.connect"}), reversible=True
        )
    )
    assert result.level == RiskLevel.MEDIUM
    assert "Elevated privileges" in result.factors
    assert "External network interaction" in result.factors


def test_three_factors_is_high_matching_doc_example() -> None:
    """Mirrors technical doc Section 12's worked example almost exactly:
    elevated privileges + external network interaction + irreversible
    modification -> HIGH.
    """
    engine = RiskEngine()
    result = engine.assess(
        RiskFactors(
            capabilities=frozenset({"process.execute", "network.connect"}),
            reversible=False,
        )
    )
    assert result.level == RiskLevel.HIGH
    assert len(result.factors) == 3


def test_all_four_factors_is_critical() -> None:
    engine = RiskEngine()
    result = engine.assess(
        RiskFactors(
            capabilities=frozenset({"process.execute", "network.connect"}),
            reversible=False,
            external_content_involved=True,
        )
    )
    assert result.level == RiskLevel.CRITICAL
    assert len(result.factors) == 4


def test_explanation_is_never_empty() -> None:
    engine = RiskEngine()
    safe = engine.assess(RiskFactors())
    risky = engine.assess(RiskFactors(reversible=False, external_content_involved=True))

    assert safe.explanation
    assert risky.explanation
    assert safe.explanation != risky.explanation


def test_assessment_provides_classification_and_explanation_together() -> None:
    """Technical doc Section 12: the risk subsystem must provide BOTH a
    classification and an explanation — not a bare score.
    """
    engine = RiskEngine()
    result = engine.assess(RiskFactors(reversible=False))
    assert result.level is not None
    assert isinstance(result.explanation, str) and len(result.explanation) > 0
