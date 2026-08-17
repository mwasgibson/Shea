from __future__ import annotations

from enum import StrEnum


class TaskState(StrEnum):
    """Task lifecycle states — technical doc Section 15 / Appendix A.

    Terminal states (no outgoing transitions): COMPLETED, CANCELLED,
    SECURITY_HALT. See state_machine.transitions.TRANSITIONS for the
    authoritative transition table and state_machine.transitions.is_terminal.
    """

    CREATED = "CREATED"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"

    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    RECOVERING = "RECOVERING"
    SECURITY_HALT = "SECURITY_HALT"


class RiskLevel(StrEnum):
    """Research doc Section 4.2 / 9.2 — risk classification, not a veto."""

    SAFE = "SAFE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class ExecutionOutcome(StrEnum):
    """Research doc Section 12.13 — SUCCESS/FAILURE/UNKNOWN must stay distinct.

    UNKNOWN is not a synonym for FAILURE: it means the system cannot
    determine whether a side effect occurred (e.g. the connection dropped
    after the action but before the result was received). Callers must not
    collapse UNKNOWN into FAILURE, since that would license unsafe retries
    of non-idempotent actions.
    """

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"


class PolicyVerdict(StrEnum):
    """Deterministic policy outcome for a set of requested capabilities.

    DENIED is the "system integrity invariant" tier (research doc Section
    15.12): it cannot be overridden by any explicit user acknowledgement.
    REQUIRES_AUTHORIZATION is the "risk warning" tier: it CAN be overridden
    by an explicit, audited user decision. Collapsing these two into one
    concept would silently make every hard block overridable — this enum
    exists specifically so that mistake is a type error, not a bug to find
    later.
    """

    ALLOWED = "ALLOWED"
    REQUIRES_AUTHORIZATION = "REQUIRES_AUTHORIZATION"
    DENIED = "DENIED"