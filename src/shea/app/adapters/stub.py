from __future__ import annotations

from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome


class StubAdapter:
    """Test double: no side effects, returns SUCCESS with echo evidence."""

    name = "stub"

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.operation.startswith("stub.") or contract.capability == "stub"

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                "echo_target": contract.target,
                "receipt_id": receipt.id,
                "attempt_id": attempt.id,
            },
        )