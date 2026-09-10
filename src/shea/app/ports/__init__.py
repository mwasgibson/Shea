from __future__ import annotations

from typing import Protocol

from shea.app.contracts import ExecutionAttempt, ExecutionReceipt


class ReceiptRepository(Protocol):
	def save(self, receipt: ExecutionReceipt) -> None: ...

	def get(self, receipt_id: str) -> ExecutionReceipt | None: ...

	def get_by_contract(self, contract_id: str) -> ExecutionReceipt | None: ...


class AttemptRepository(Protocol):
	def save(self, attempt: ExecutionAttempt) -> None: ...

	def list_by_receipt(self, receipt_id: str) -> list[ExecutionAttempt]: ...


__all__ = ["AttemptRepository", "ReceiptRepository"]
