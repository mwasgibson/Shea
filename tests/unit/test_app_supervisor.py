from __future__ import annotations

from datetime import UTC, datetime

from shea.app.adapters.stub import StubAdapter
from shea.app.contracts import ExecutionContract
from shea.app.enums import AppOutcome, AttemptState, ReceiptState
from shea.app.memory import (
    InMemoryAttemptRepository,
    InMemoryReceiptRepository,
)
from shea.app.supervisor import ExecutionSupervisor


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class _Ids:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"app-{self._n}"


class _Uow:
    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_supervisor_persists_receipt_before_success() -> None:
    receipts = InMemoryReceiptRepository()
    attempts = InMemoryAttemptRepository()
    supervisor = ExecutionSupervisor(
        adapters=[StubAdapter()],
        receipt_repository=receipts,  # type: ignore[arg-type]
        attempt_repository=attempts,  # type: ignore[arg-type]
        clock=_Clock(),  # type: ignore[arg-type]
        id_generator=_Ids(),  # type: ignore[arg-type]
        unit_of_work=_Uow(),  # type: ignore[arg-type]
    )
    contract = ExecutionContract(
        contract_id="c1",
        authorization_id="a1",
        capability="stub",
        operation="stub.echo",
        target="unit-test",
    )
    result = supervisor.execute(contract)

    assert result.receipt.state is ReceiptState.FINALIZED
    assert result.attempt.state is AttemptState.FINALIZED
    assert result.adapter_result.outcome is AppOutcome.SUCCESS
    assert receipts.get(result.receipt.id) is not None
    assert result.adapter_result.evidence["receipt_id"] == result.receipt.id