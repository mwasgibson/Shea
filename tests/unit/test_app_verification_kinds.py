"""Verification must be *satisfiable*, and must never turn "we don't know"
into "it failed".

Two regressions are pinned here. (1) Policy and evidence drifted apart —
policies required "adapter.browser", evidence was stamped "adapter.browse",
and operations without a policy fell to a catch-all that demanded
"adapter.generic" — so browser.*, application.terminate and
filesystem.inspect could never verify as SUCCESS. (2) Missing evidence
overwrote an adapter-reported UNKNOWN with FAILURE.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shea.app.contracts import AdapterResult
from shea.app.enums import AppOutcome, EvidenceStrength
from shea.app.verification import (
    DEFAULT_POLICIES,
    VerificationPolicy,
    evidence_kind_for_operation,
    policy_for_operation,
)
from shea.app.verify_engine import evaluate_verification, evidence_from_adapter

NOW = datetime(2026, 1, 1, tzinfo=UTC)

ALL_OPERATIONS = [
    "filesystem.read", "filesystem.write", "filesystem.create", "filesystem.delete",
    "filesystem.copy", "filesystem.move", "filesystem.inspect",
    "process.run", "process.spawn", "process.execute",
    "application.launch", "application.activate", "application.inspect",
    "application.terminate",
    "browser.navigate", "browser.read", "browser.download", "browser.upload",
    "network.request", "network.connect", "http.fetch",
]  # fmt: skip


def _verify(op: str, result: AdapterResult, policy: VerificationPolicy | None = None) -> AppOutcome:
    evidence = evidence_from_adapter(
        evidence_id="e", receipt_id="r", attempt_id="a", operation=op, result=result,
        observed_at=NOW,
    )  # fmt: skip
    return evaluate_verification(
        verification_id="v", receipt_id="r", attempt_id="a",
        policy=policy or policy_for_operation(op), adapter_result=result,
        evidence=evidence, verified_at=NOW,
    ).result  # fmt: skip


@pytest.mark.parametrize("operation", ALL_OPERATIONS)
def test_every_operations_policy_accepts_the_evidence_the_engine_produces(operation: str) -> None:
    policy = policy_for_operation(operation)
    kind = evidence_kind_for_operation(operation)
    assert kind in policy.required_evidence_kinds, (
        f"{operation}: policy {policy.policy_id} requires "
        f"{set(policy.required_evidence_kinds)} but evidence is stamped {kind!r}"
    )


def test_every_explicit_policy_is_satisfiable_by_its_own_operations_evidence() -> None:
    for operation, policy in DEFAULT_POLICIES.items():
        if operation == "default":
            continue
        assert evidence_kind_for_operation(operation) in policy.required_evidence_kinds, operation


@pytest.mark.parametrize(
    "operation",
    ["application.terminate", "filesystem.inspect", "browser.download", "process.spawn"],
)
def test_operations_without_their_own_policy_can_still_verify_as_success(operation: str) -> None:
    assert _verify(operation, AdapterResult(outcome=AppOutcome.SUCCESS)) is AppOutcome.SUCCESS


def test_browser_navigation_with_correct_evidence_verifies_as_success() -> None:
    result = AdapterResult(outcome=AppOutcome.SUCCESS, evidence={"postcondition": "page_fetched"})
    assert _verify("browser.navigate", result) is AppOutcome.SUCCESS


_NEEDS_OTHER_KIND = VerificationPolicy(
    policy_id="test.v1",
    required_evidence_kinds=frozenset({"adapter.something-else"}),
    missing_evidence_outcome=AppOutcome.FAILURE,
)
_NEEDS_STRONGER = VerificationPolicy(
    policy_id="test.strength.v1",
    required_evidence_kinds=frozenset({"adapter.process"}),
    minimum_strength=EvidenceStrength.DIRECT,
    missing_evidence_outcome=AppOutcome.FAILURE,
)


def test_missing_evidence_never_downgrades_unknown_to_failure() -> None:
    unknown = AdapterResult(outcome=AppOutcome.UNKNOWN, error="timeout after request was sent")
    assert _verify("process.run", unknown, _NEEDS_OTHER_KIND) is AppOutcome.UNKNOWN


def test_missing_evidence_still_prevents_success() -> None:
    success = AdapterResult(outcome=AppOutcome.SUCCESS)
    assert _verify("process.run", success, _NEEDS_OTHER_KIND) is AppOutcome.FAILURE


def test_missing_evidence_leaves_a_reported_failure_a_failure() -> None:
    failure = AdapterResult(outcome=AppOutcome.FAILURE, error="boom")
    assert _verify("process.run", failure, _NEEDS_OTHER_KIND) is AppOutcome.FAILURE


def test_unverified_transport_keeps_unknown_unknown() -> None:
    unknown = AdapterResult(outcome=AppOutcome.UNKNOWN, error="connection dropped")
    assert _verify("network.request", unknown) is AppOutcome.UNKNOWN
