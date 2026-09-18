from __future__ import annotations

import os

from shea.app.contracts import ExecutionAttempt, ExecutionReceipt
from shea.app.enums import AppOutcome
from shea.app.reconcile.base import ReconcileObservation


class ProcessReconciler:
    """Reconcile process.* via PID liveness only — never re-spawn."""

    name = "process"

    def supports(self, receipt: ExecutionReceipt) -> bool:
        op = receipt.operation or ""
        return op.startswith("process.") or (receipt.capability or "").startswith(
            "process."
        )

    def observe(
        self,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt | None,
        *,
        stuck_reason: str,
    ) -> ReconcileObservation:
        evidence = dict(attempt.evidence) if attempt and attempt.evidence else {}
        meta = dict(receipt.metadata or {})
        pid_raw = evidence.get("pid") or meta.get("pid")
        if pid_raw is None:
            if stuck_reason == "attempt_invoked_not_finalized":
                return ReconcileObservation(
                    outcome=AppOutcome.UNKNOWN,
                    detail="process invoke without recorded pid",
                )
            return ReconcileObservation(
                outcome=AppOutcome.FAILURE,
                detail="process never recorded a pid",
            )

        try:
            pid = int(pid_raw)
        except (TypeError, ValueError):
            return ReconcileObservation(
                outcome=AppOutcome.UNKNOWN,
                detail=f"unparseable pid {pid_raw!r}",
            )

        alive = self._pid_alive(pid)
        op = receipt.operation or ""

        if "terminate" in op or "kill" in op:
            if not alive:
                return ReconcileObservation(
                    outcome=AppOutcome.SUCCESS,
                    detail="terminate postcondition: pid not alive",
                    evidence={"pid": pid, "alive": False},
                    side_effect_detected=True,
                )
            return ReconcileObservation(
                outcome=AppOutcome.UNKNOWN
                if stuck_reason == "attempt_invoked_not_finalized"
                else AppOutcome.FAILURE,
                detail="pid still alive after terminate attempt",
                evidence={"pid": pid, "alive": True},
            )

        # spawn / run
        if alive:
            return ReconcileObservation(
                outcome=AppOutcome.SUCCESS,
                detail="process still alive",
                evidence={"pid": pid, "alive": True},
                side_effect_detected=True,
            )
        if stuck_reason == "attempt_invoked_not_finalized":
            return ReconcileObservation(
                outcome=AppOutcome.UNKNOWN,
                detail="pid gone; exit status unknown",
                evidence={"pid": pid, "alive": False},
            )
        return ReconcileObservation(
            outcome=AppOutcome.FAILURE,
            detail="process not alive and never finalized",
            evidence={"pid": pid, "alive": False},
        )

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but not owned by us
        except OSError:
            return False