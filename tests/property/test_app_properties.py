from __future__ import annotations

from shea.app.adapters.stub import StubAdapter
from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.unit_of_work import UnitOfWork


class RecordingAdapter(StubAdapter):
    def __init__(self) -> None:
        self.invocations = 0

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        self.invocations += 1
        return super().invoke(contract, receipt, attempt)


class DroppingReceiptRepo:
    """Pretends save worked but get always returns None."""

    def save(self, receipt: ExecutionReceipt) -> None:
        return None

    def get(self, receipt_id: str) -> ExecutionReceipt | None:
        return None

    def get_by_contract(self, contract_id: str) -> ExecutionReceipt | None:
        return None


def test_no_durable_receipt_means_no_adapter_invoke(
    clock: Clock, id_generator: IdGenerator, unit_of_work: UnitOfWork
    ):
    # or use the local _Clock/_Ids/_Uow from the other test
    ...