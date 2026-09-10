from __future__ import annotations


class AppPlaneError(Exception):
    pass


class ContractValidationError(AppPlaneError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Execution contract invalid: {reason}")


class ReceiptRequiredError(AppPlaneError):
    """Raised if an adapter would run without a durable receipt."""

    def __init__(self, contract_id: str) -> None:
        self.contract_id = contract_id
        super().__init__(
            f"Refusing invoke for contract {contract_id!r}: no durable receipt"
        )