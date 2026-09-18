from __future__ import annotations

from shea.app.contracts import ExecutionAttempt, ExecutionReceipt
from shea.app.reconcile.application import ApplicationReconciler
from shea.app.reconcile.base import OperationReconciler, ReconcileObservation
from shea.app.reconcile.default import DefaultReconciler
from shea.app.reconcile.filesystem import FilesystemReconciler
from shea.app.reconcile.network import NetworkReconciler
from shea.app.reconcile.process import ProcessReconciler


class ReconcilerRegistry:
    def __init__(self, reconcilers: list[OperationReconciler] | None = None) -> None:
        self._reconcilers = list(reconcilers or [])
        self._default = DefaultReconciler()

    def register(self, reconciler: OperationReconciler) -> None:
        self._reconcilers.append(reconciler)

    def select(self, receipt: ExecutionReceipt) -> OperationReconciler:
        for r in self._reconcilers:
            if r.supports(receipt):
                return r
        return self._default

    def observe(
        self,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt | None,
        *,
        stuck_reason: str,
    ) -> ReconcileObservation:
        return self.select(receipt).observe(
            receipt, attempt, stuck_reason=stuck_reason
        )


def default_reconciler_registry() -> ReconcilerRegistry:
    return ReconcilerRegistry(
        [
            FilesystemReconciler(),
            ProcessReconciler(),
            NetworkReconciler(),
            ApplicationReconciler(),
        ]
    )