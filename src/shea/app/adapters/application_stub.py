from __future__ import annotations

from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome


class ApplicationStubAdapter:
    """Phase 3 placeholder — real app control is Phase 6 platform work."""

    name = "application.stub"

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.operation.startswith("application.") or contract.capability in {
            "application.launch",
            "application.activate",
            "application.terminate",
        }

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        return AdapterResult(
            outcome=AppOutcome.FAILURE,
            error="application control not implemented in V1 (adapter=application.stub)",
            evidence={
                "receipt_id": receipt.id,
                "attempt_id": attempt.id,
                "operation": contract.operation,
                "supported": False,
            },
        )