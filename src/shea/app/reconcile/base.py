from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from shea.app.contracts import ExecutionAttempt, ExecutionReceipt
from shea.app.enums import AppOutcome


@dataclass(frozen=True)
class ReconcileObservation:
    """What we learned about external state without re-invoking the adapter.

    SUCCESS / FAILURE only when external state is known.
    UNKNOWN means still unknowable — must not invent certainty.
    """

    outcome: AppOutcome
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict[str, Any])
    side_effect_detected: bool = False


class OperationReconciler(Protocol):
    """Observe external world for one class of operations.

    Must never perform the original side effect again.
    Must never upgrade UNKNOWN to SUCCESS/FAILURE without observable evidence.
    """

    name: str

    def supports(self, receipt: ExecutionReceipt) -> bool:
        ...

    def observe(
        self,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt | None,
        *,
        stuck_reason: str,
    ) -> ReconcileObservation:
        ...