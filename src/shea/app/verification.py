from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from shea.app.enums import AppOutcome, EvidenceStrength


@dataclass(frozen=True)
class VerificationPolicy:
    policy_id: str
    postconditions: tuple[str, ...] = ()
    required_evidence_kinds: frozenset[str] = frozenset()
    minimum_strength: EvidenceStrength = EvidenceStrength.DIRECT
    missing_evidence_outcome: AppOutcome = AppOutcome.FAILURE
    requires_transport_verification: bool = False
    # If adapter says SUCCESS but postcondition fails → FAILURE
    # If adapter says UNKNOWN → stay UNKNOWN unless policy forces FAILURE
    contradiction_behavior: str = "fail"  # fail | unknown


@dataclass(frozen=True)
class AppVerificationRecord:
    id: str
    receipt_id: str
    attempt_id: str
    policy_id: str
    expected_postconditions: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    result: AppOutcome
    explanation: str
    verified_at: datetime


# Built-in policies keyed by operation prefix / name
DEFAULT_POLICIES: dict[str, VerificationPolicy] = {
    "filesystem.write": VerificationPolicy(
        policy_id="fs.write.v1",
        postconditions=("content_match", "exists"),
        required_evidence_kinds=frozenset({"adapter.filesystem"}),
    ),
    "filesystem.create": VerificationPolicy(
        policy_id="fs.create.v1",
        postconditions=("exists",),
        required_evidence_kinds=frozenset({"adapter.filesystem"}),
    ),
    "filesystem.delete": VerificationPolicy(
        policy_id="fs.delete.v1",
        postconditions=("absent",),
        required_evidence_kinds=frozenset({"adapter.filesystem"}),
    ),
    "filesystem.copy": VerificationPolicy(
        policy_id="fs.copy.v1",
        postconditions=("source_and_destination_exist",),
        required_evidence_kinds=frozenset({"adapter.filesystem"}),
    ),
    "filesystem.move": VerificationPolicy(
        policy_id="fs.move.v1",
        postconditions=("source_absent_destination_exists",),
        required_evidence_kinds=frozenset({"adapter.filesystem"}),
    ),
    "filesystem.read": VerificationPolicy(
        policy_id="fs.read.v1",
        postconditions=(),
        required_evidence_kinds=frozenset({"adapter.filesystem"}),
    ),
    "process.run": VerificationPolicy(
        policy_id="process.run.v1",
        postconditions=(),
        required_evidence_kinds=frozenset({"adapter.process"}),
    ),
    "default": VerificationPolicy(
        policy_id="default.v1",
        postconditions=(),
        required_evidence_kinds=frozenset({"adapter.generic"}),
    ),
    "network.request": VerificationPolicy(
        policy_id="net.request.v1",
        postconditions=("response_received",),
        required_evidence_kinds=frozenset({"adapter.network"}),
        requires_transport_verification=True,
    ),
    "http.fetch": VerificationPolicy(
        policy_id="http.fetch.v1",
        postconditions=("response_received",),
        required_evidence_kinds=frozenset({"adapter.network"}),
        requires_transport_verification=True,
    ),
    "application.launch": VerificationPolicy(
        policy_id="app.launch.v1",
        postconditions=("open_accepted",),
        required_evidence_kinds=frozenset({"adapter.application"}),
    ),
    "application.activate": VerificationPolicy(
        policy_id="app.activate.v1",
        postconditions=("open_accepted",),
        required_evidence_kinds=frozenset({"adapter.application"}),
    ),
    "application.inspect": VerificationPolicy(
        policy_id="app.inspect.v1",
        postconditions=("inspect_platform",),
        required_evidence_kinds=frozenset({"adapter.application"}),
    ),
    "browser.navigate": VerificationPolicy(
        policy_id="browser.navigate.v1",
        postconditions=("page_fetched",),
        required_evidence_kinds=frozenset({"adapter.browser"}),
    ),
    "browser.read": VerificationPolicy(
        policy_id="browser.read.v1",
        postconditions=("page_fetched",),
        required_evidence_kinds=frozenset({"adapter.browser"}),
    ),
}


# The evidence `kind` an adapter's result is stamped with, by operation
# family. This is the single source of truth: `evidence_from_adapter`
# stamps with it and the family fallback policies below require it, so the
# two can never drift apart (they once did: policies required
# "adapter.browser" while evidence was stamped "adapter.browse", making
# every browser operation unverifiable).
EVIDENCE_KIND_BY_FAMILY: dict[str, str] = {
    "filesystem": "adapter.filesystem",
    "process": "adapter.process",
    "network": "adapter.network",
    "application": "adapter.application",
    "browser": "adapter.browser",
}


def evidence_kind_for_operation(operation: str) -> str:
    if operation == "http.fetch":
        return EVIDENCE_KIND_BY_FAMILY["network"]
    family = operation.split(".", 1)[0]
    return EVIDENCE_KIND_BY_FAMILY.get(family, "adapter.generic")


# An operation with no policy of its own is verified against its family:
# the adapter's own evidence of the right kind must be present. This is
# deliberately no stronger than the old catch-all — it adds no postconditions
# — but unlike it, it can actually be satisfied (the catch-all demanded
# "adapter.generic" evidence that no family adapter ever produces).
_FAMILY_POLICIES: dict[str, VerificationPolicy] = {
    family: VerificationPolicy(
        policy_id=f"{family}.family.v1",
        required_evidence_kinds=frozenset({kind}),
    )
    for family, kind in EVIDENCE_KIND_BY_FAMILY.items()
}


def policy_for_operation(operation: str) -> VerificationPolicy:
    exact = DEFAULT_POLICIES.get(operation)
    if exact is not None:
        return exact
    family = _FAMILY_POLICIES.get(operation.split(".", 1)[0])
    return family if family is not None else DEFAULT_POLICIES["default"]