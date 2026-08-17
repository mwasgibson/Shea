from __future__ import annotations

from dataclasses import dataclass

from shea.contracts.enums import RiskLevel


@dataclass(frozen=True)
class ConfirmationRule:
    """One row of research doc Section 4.2's risk/behavior table.

    `requires_authorization=False` means the task may proceed without any
    human decision (SAFE, LOW: informational at most). `requires_
    authorization=True, requires_explicit_acknowledgement=False` is the
    MEDIUM tier — "optional acknowledgement": a warning is recorded, but
    the system may proceed with an implicit, non-explicit authorization if
    the caller doesn't supply one. `requires_explicit_acknowledgement=True`
    (HIGH, CRITICAL, UNKNOWN) means the task is blocked until an explicit,
    auditable user acknowledgement is provided — no implicit path exists.
    """

    requires_authorization: bool
    requires_explicit_acknowledgement: bool


# research doc Section 4.2:
#   SAFE     -> Execute normally.
#   LOW      -> Informational warning if useful.
#   MEDIUM   -> Warn + optional acknowledgement.
#   HIGH     -> Strong warning + explicit acknowledgement.
#   CRITICAL -> Strong warning + explicit acknowledgement.
#   UNKNOWN  -> Warn that risk is uncertain + user decides.
CONFIRMATION_RULES: dict[RiskLevel, ConfirmationRule] = {
    RiskLevel.SAFE: ConfirmationRule(False, False),
    RiskLevel.LOW: ConfirmationRule(False, False),
    RiskLevel.MEDIUM: ConfirmationRule(True, False),
    RiskLevel.HIGH: ConfirmationRule(True, True),
    RiskLevel.CRITICAL: ConfirmationRule(True, True),
    RiskLevel.UNKNOWN: ConfirmationRule(True, True),
}


def confirmation_rule_for(level: RiskLevel) -> ConfirmationRule:
    return CONFIRMATION_RULES[level]