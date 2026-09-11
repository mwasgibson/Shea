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
        required_evidence_kinds=frozenset(),
    ),
}


def policy_for_operation(operation: str) -> VerificationPolicy:
    return DEFAULT_POLICIES.get(operation, DEFAULT_POLICIES["default"])