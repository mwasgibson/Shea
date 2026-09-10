from __future__ import annotations

from typing import Protocol

from shea.app.contracts import AdapterResult, ExecutionAttempt, ExecutionContract, ExecutionReceipt


class Adapter(Protocol):
    """Platform mechanism. Returns facts/evidence only; never grants authority."""

    name: str

    def supports(self, contract: ExecutionContract) -> bool: ...

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult: ...