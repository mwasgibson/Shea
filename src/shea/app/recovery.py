from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shea.app.enums import AppOutcome, AttemptState, ReceiptState, RecoveryStatus
from shea.app.contracts import ExecutionAttempt, ExecutionReceipt


@dataclass
class RecoveryIncident:
    id: str
    receipt_id: str
    attempt_id: str | None
    status: RecoveryStatus
    reason: str
    created_at: datetime
    updated_at: datetime
    resolution: str | None = None
    fence_token: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReconciliationResult:
    receipt: ExecutionReceipt
    attempt: ExecutionAttempt | None
    incident: RecoveryIncident | None
    outcome: AppOutcome
    detail: str


def classify_stuck_attempt(
    receipt: ExecutionReceipt,
    attempt: ExecutionAttempt | None,
) -> str | None:
    """Return reason if this execution needs reconciliation."""
    if receipt.state is ReceiptState.FINALIZED:
        return None
    if attempt is None:
        return "receipt_without_attempt"
    if attempt.state is AttemptState.INVOKED:
        return "attempt_invoked_not_finalized"
    if attempt.state is AttemptState.CREATED and receipt.state is ReceiptState.ATTEMPTING:
        return "attempt_created_not_invoked"
    if receipt.state is ReceiptState.ATTEMPTING:
        return "receipt_attempting"
    return None