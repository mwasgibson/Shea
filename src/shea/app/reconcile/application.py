from __future__ import annotations

from shea.app.contracts import ExecutionAttempt, ExecutionReceipt
from shea.app.enums import AppOutcome
from shea.app.reconcile.base import ReconcileObservation


class ApplicationReconciler:
    """Application launch/terminate — V1 conservatively keeps UNKNOWN.

    Platform-specific process/bundle inspection can deepen this later.
    """

    name = "application"

    def supports(self, receipt: ExecutionReceipt) -> bool:
        op = receipt.operation or ""
        return op.startswith("application.") or op.startswith("app.")

    def observe(
        self,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt | None,
        *,
        stuck_reason: str,
    ) -> ReconcileObservation:
        evidence = dict(attempt.evidence) if attempt and attempt.evidence else {}
        if evidence.get("launched") is True or evidence.get("terminated") is True:
            return ReconcileObservation(
                outcome=AppOutcome.SUCCESS,
                detail="application evidence present on attempt",
                evidence=evidence,
                side_effect_detected=True,
            )
        if stuck_reason == "attempt_invoked_not_finalized":
            return ReconcileObservation(
                outcome=AppOutcome.UNKNOWN,
                detail="application side effect may have occurred",
                evidence=evidence,
            )
        return ReconcileObservation(
            outcome=AppOutcome.FAILURE,
            detail="application operation never invoked",
            evidence=evidence,
        )