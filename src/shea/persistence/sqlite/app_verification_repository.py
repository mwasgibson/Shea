from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from shea.app.enums import AppOutcome
from shea.app.verification import AppVerificationRecord
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


class SqliteAppVerificationRepository:
    def __init__(
        self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork
    ) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save(self, record: AppVerificationRecord) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO app_verifications (
                    id, receipt_id, attempt_id, policy_id,
                    expected_postconditions, evidence_ids,
                    result, explanation, verified_at
                ) VALUES (
                    :id, :receipt_id, :attempt_id, :policy_id,
                    :expected_postconditions, :evidence_ids,
                    :result, :explanation, :verified_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    policy_id = excluded.policy_id,
                    expected_postconditions = excluded.expected_postconditions,
                    evidence_ids = excluded.evidence_ids,
                    result = excluded.result,
                    explanation = excluded.explanation,
                    verified_at = excluded.verified_at
                """,
                {
                    "id": record.id,
                    "receipt_id": record.receipt_id,
                    "attempt_id": record.attempt_id,
                    "policy_id": record.policy_id,
                    "expected_postconditions": json.dumps(
                        list(record.expected_postconditions)
                    ),
                    "evidence_ids": json.dumps(list(record.evidence_ids)),
                    "result": record.result.value,
                    "explanation": record.explanation,
                    "verified_at": record.verified_at.isoformat(),
                },
            )

    def get_latest_by_receipt(self, receipt_id: str) -> AppVerificationRecord | None:
        row = self._conn.execute(
            """
            SELECT * FROM app_verifications
            WHERE receipt_id = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (receipt_id,),
        ).fetchone()
        return _row_to_verification(row) if row is not None else None


def _row_to_verification(row: sqlite3.Row) -> AppVerificationRecord:
    expected = json.loads(row["expected_postconditions"] or "[]")
    evidence_ids = json.loads(row["evidence_ids"] or "[]")
    return AppVerificationRecord(
        id=row["id"],
        receipt_id=row["receipt_id"],
        attempt_id=row["attempt_id"],
        policy_id=row["policy_id"],
        expected_postconditions=tuple(expected),
        evidence_ids=tuple(evidence_ids),
        result=AppOutcome(row["result"]),
        explanation=row["explanation"],
        verified_at=datetime.fromisoformat(row["verified_at"]),
    )