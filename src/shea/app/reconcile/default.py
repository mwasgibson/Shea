from __future__ import annotations

from shea.app.contracts import ExecutionAttempt, ExecutionReceipt
from shea.app.enums import AppOutcome
from shea.app.reconcile.base import ReconcileObservation


class DefaultReconciler:
    """Fallback: preserve UNKNOWN semantics when nothing domain-specific applies."""

    name = "default"

    def supports(self, receipt: ExecutionReceipt) -> bool:
        return True

    def observe(
        self,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt | None,
        *,
        stuck_reason: str,
    ) -> ReconcileObservation:
        if stuck_reason == "attempt_invoked_not_finalized":
            return ReconcileObservation(
                outcome=AppOutcome.UNKNOWN,
                detail=f"default: {stuck_reason}; external state unknowable",
            )
        return ReconcileObservation(
            outcome=AppOutcome.FAILURE,
            detail=f"default: {stuck_reason}; no side effect claimed",
        )