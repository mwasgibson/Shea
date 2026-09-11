from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from shea.app.enums import RecoveryStatus
from shea.app.recovery import RecoveryIncident
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


class SqliteAppRecoveryRepository:
    def __init__(
        self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork
    ) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save_incident(self, incident: RecoveryIncident) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO app_recovery_incidents (
                    id, receipt_id, attempt_id, status, reason,
                    created_at, updated_at, resolution, fence_token, metadata
                ) VALUES (
                    :id, :receipt_id, :attempt_id, :status, :reason,
                    :created_at, :updated_at, :resolution, :fence_token, :metadata
                )
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at,
                    resolution = excluded.resolution,
                    fence_token = excluded.fence_token,
                    metadata = excluded.metadata
                """,
                {
                    "id": incident.id,
                    "receipt_id": incident.receipt_id,
                    "attempt_id": incident.attempt_id,
                    "status": incident.status.value,
                    "reason": incident.reason,
                    "created_at": incident.created_at.isoformat(),
                    "updated_at": incident.updated_at.isoformat(),
                    "resolution": incident.resolution,
                    "fence_token": incident.fence_token,
                    "metadata": json.dumps(incident.metadata or {}),
                },
            )

    def list_open(self) -> list[RecoveryIncident]:
        rows = self._conn.execute(
            """
            SELECT * FROM app_recovery_incidents
            WHERE status IN ('OPEN', 'RECONCILING', 'QUARANTINED')
            ORDER BY rowid ASC
            """
        ).fetchall()
        return [_row_to_incident(row) for row in rows]


def _row_to_incident(row: sqlite3.Row) -> RecoveryIncident:
    metadata: dict[str, Any] = json.loads(row["metadata"] or "{}")
    return RecoveryIncident(
        id=row["id"],
        receipt_id=row["receipt_id"],
        attempt_id=row["attempt_id"],
        status=RecoveryStatus(row["status"]),
        reason=row["reason"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        resolution=row["resolution"],
        fence_token=row["fence_token"],
        metadata=metadata,
    )