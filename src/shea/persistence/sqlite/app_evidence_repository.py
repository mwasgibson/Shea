from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from shea.app.enums import EvidenceStrength
from shea.app.evidence import EvidenceRecord
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


class SqliteAppEvidenceRepository:
    def __init__(
        self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork
    ) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save(self, record: EvidenceRecord) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO app_evidence (
                    id, receipt_id, attempt_id, kind, source, strength,
                    observed_at, content_hash, payload, sensitivity
                ) VALUES (
                    :id, :receipt_id, :attempt_id, :kind, :source, :strength,
                    :observed_at, :content_hash, :payload, :sensitivity
                )
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    source = excluded.source,
                    strength = excluded.strength,
                    observed_at = excluded.observed_at,
                    content_hash = excluded.content_hash,
                    payload = excluded.payload,
                    sensitivity = excluded.sensitivity
                """,
                {
                    "id": record.id,
                    "receipt_id": record.receipt_id,
                    "attempt_id": record.attempt_id,
                    "kind": record.kind,
                    "source": record.source,
                    "strength": record.strength.value,
                    "observed_at": record.observed_at.isoformat(),
                    "content_hash": record.content_hash,
                    "payload": json.dumps(record.payload),
                    "sensitivity": record.sensitivity,
                },
            )

    def list_by_receipt(self, receipt_id: str) -> list[EvidenceRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM app_evidence
            WHERE receipt_id = ?
            ORDER BY rowid ASC
            """,
            (receipt_id,),
        ).fetchall()
        return [_row_to_evidence(row) for row in rows]


def _row_to_evidence(row: sqlite3.Row) -> EvidenceRecord:
    payload: dict[str, Any] = json.loads(row["payload"] or "{}")
    return EvidenceRecord(
        id=row["id"],
        receipt_id=row["receipt_id"],
        attempt_id=row["attempt_id"],
        kind=row["kind"],
        source=row["source"],
        strength=EvidenceStrength(row["strength"]),
        observed_at=datetime.fromisoformat(row["observed_at"]),
        content_hash=row["content_hash"],
        payload=payload,
        sensitivity=row["sensitivity"] or "normal",
    )