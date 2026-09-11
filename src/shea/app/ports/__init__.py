from __future__ import annotations

from typing import Protocol

from shea.app.contracts import ExecutionAttempt, ExecutionReceipt
from shea.app.evidence import EvidenceRecord
from shea.app.idempotency import IdempotencyRecord
from shea.app.recovery import RecoveryIncident
from shea.app.verification import AppVerificationRecord


class ReceiptRepository(Protocol):
	def save(self, receipt: ExecutionReceipt) -> None: ...

	def get(self, receipt_id: str) -> ExecutionReceipt | None: ...

	def get_by_contract(self, contract_id: str) -> ExecutionReceipt | None: ...


class AttemptRepository(Protocol):
	def save(self, attempt: ExecutionAttempt) -> None: ...

	def list_by_receipt(self, receipt_id: str) -> list[ExecutionAttempt]: ...


class EvidenceRepository(Protocol):
	def save(self, record: EvidenceRecord) -> None: ...

	def list_by_receipt(self, receipt_id: str) -> list[EvidenceRecord]: ...


class AppVerificationRepository(Protocol):
	def save(self, record: AppVerificationRecord) -> None: ...

	def get_latest_by_receipt(self, receipt_id: str) -> AppVerificationRecord | None: ...


class IdempotencyRepository(Protocol):
	def get(self, key: str) -> IdempotencyRecord | None: ...

	def save(self, record: IdempotencyRecord) -> None: ...


class RecoveryRepository(Protocol):
	def save_incident(self, incident: RecoveryIncident) -> None: ...

	def list_open(self) -> list[RecoveryIncident]: ...


__all__ = [
	"AppVerificationRepository",
	"AttemptRepository",
	"EvidenceRepository",
	"IdempotencyRepository",
	"ReceiptRepository",
	"RecoveryRepository",
]
