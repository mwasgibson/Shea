from __future__ import annotations

from shea.app.contracts import ExecutionAttempt, ExecutionReceipt


class InMemoryReceiptRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, ExecutionReceipt] = {}

    def save(self, receipt: ExecutionReceipt) -> None:
        self._by_id[receipt.id] = receipt

    def get(self, receipt_id: str) -> ExecutionReceipt | None:
        return self._by_id.get(receipt_id)

    def get_by_contract(self, contract_id: str) -> ExecutionReceipt | None:
        for r in self._by_id.values():
            if r.contract_id == contract_id:
                return r
        return None


class InMemoryAttemptRepository:
    def __init__(self) -> None:
        self._items: list[ExecutionAttempt] = []

    def save(self, attempt: ExecutionAttempt) -> None:
        self._items = [a for a in self._items if a.id != attempt.id]
        self._items.append(attempt)

    def list_by_receipt(self, receipt_id: str) -> list[ExecutionAttempt]:
        return [a for a in self._items if a.receipt_id == receipt_id]