from __future__ import annotations

from shea.app.contracts import ExecutionAttempt, ExecutionReceipt
from shea.app.enums import AppOutcome
from shea.app.reconcile.base import ReconcileObservation


class NetworkReconciler:
    """Network side effects are not safely observable after the fact in V1.

    HTTP may have completed before a timeout. Never claim SUCCESS/FAILURE
    without response evidence already on the attempt.
    """

    name = "network"

    def supports(self, receipt: ExecutionReceipt) -> bool:
        op = receipt.operation or ""
        cap = receipt.capability or ""
        return (
            op.startswith("network.")
            or op.startswith("http.")
            or op.startswith("browser.")
            or cap.startswith("network.")
        )

    def observe(
        self,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt | None,
        *,
        stuck_reason: str,
    ) -> ReconcileObservation:
        evidence = dict(attempt.evidence) if attempt and attempt.evidence else {}
        if "status_code" in evidence or evidence.get("postcondition") == "response_received":
            return ReconcileObservation(
                outcome=AppOutcome.SUCCESS,
                detail="response evidence already present on attempt",
                evidence=evidence,
                side_effect_detected=True,
            )
        if stuck_reason == "attempt_invoked_not_finalized":
            return ReconcileObservation(
                outcome=AppOutcome.UNKNOWN,
                detail=(
                    "network/browser invoke without response evidence; "
                    "side effect may have occurred (UNKNOWN ≠ FAILURE)"
                ),
                evidence=evidence,
            )
        return ReconcileObservation(
            outcome=AppOutcome.FAILURE,
            detail="network operation never reached durable invoke",
            evidence=evidence,
        )