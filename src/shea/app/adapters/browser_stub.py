from __future__ import annotations

from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome


class BrowserStubAdapter:
    """Phase 5 placeholder — real browser control is later."""

    name = "browser.stub"

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.operation.startswith("browser.") or contract.capability in {
            "browser.navigate",
            "browser.read",
        }

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        return AdapterResult(
            outcome=AppOutcome.FAILURE,
            error="browser control not implemented in V1 (adapter=browser.stub)",
            evidence={
                "receipt_id": receipt.id,
                "attempt_id": attempt.id,
                "operation": contract.operation,
                "supported": False,
            },
        )