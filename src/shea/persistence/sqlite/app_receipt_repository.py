from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from shea.app.contracts import ExecutionReceipt
from shea.app.enums import AppOutcome, ReceiptState
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class SqliteAppReceiptRepository:
    def __init__(
        self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork
    ) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save(self, receipt: ExecutionReceipt) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO app_receipts (
                    id, contract_id, authorization_id, capability, operation,
                    target, state, created_at, finalized_at, outcome,
                    adapter_name, metadata
                ) VALUES (
                    :id, :contract_id, :authorization_id, :capability, :operation,
                    :target, :state, :created_at, :finalized_at, :outcome,
                    :adapter_name, :metadata
                )
                ON CONFLICT(id) DO UPDATE SET
                    state = excluded.state,
                    finalized_at = excluded.finalized_at,
                    outcome = excluded.outcome,
                    adapter_name = excluded.adapter_name,
                    metadata = excluded.metadata
                """,
                {
                    "id": receipt.id,
                    "contract_id": receipt.contract_id,
                    "authorization_id": receipt.authorization_id,
                    "capability": receipt.capability,
                    "operation": receipt.operation,
                    "target": receipt.target,
                    "state": receipt.state.value,
                    "created_at": receipt.created_at.isoformat(),
                    "finalized_at": (
                        receipt.finalized_at.isoformat()
                        if receipt.finalized_at
                        else None
                    ),
                    "outcome": receipt.outcome.value if receipt.outcome else None,
                    "adapter_name": receipt.adapter_name,
                    "metadata": json.dumps(receipt.metadata),
                },
            )

    def get(self, receipt_id: str) -> ExecutionReceipt | None:
        row = self._conn.execute(
            "SELECT * FROM app_receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        return _row_to_receipt(row) if row is not None else None

    def get_by_contract(self, contract_id: str) -> ExecutionReceipt | None:
        row = self._conn.execute(
            """
            SELECT * FROM app_receipts
            WHERE contract_id = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (contract_id,),
        ).fetchone()
        return _row_to_receipt(row) if row is not None else None


def _row_to_receipt(row: sqlite3.Row) -> ExecutionReceipt:
    return ExecutionReceipt(
        id=row["id"],
        contract_id=row["contract_id"],
        authorization_id=row["authorization_id"],
        capability=row["capability"],
        operation=row["operation"],
        target=row["target"],
        state=ReceiptState(row["state"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        finalized_at=_parse_dt(row["finalized_at"]),
        outcome=AppOutcome(row["outcome"]) if row["outcome"] else None,
        adapter_name=row["adapter_name"],
        metadata=json.loads(row["metadata"] or "{}"),
    )