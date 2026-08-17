from __future__ import annotations

import json
import sqlite3

from shea.contracts.enums import RiskLevel
from shea.contracts.models import Decision


class SqliteDecisionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, decision: Decision) -> None:
        self._conn.execute(
            """
            INSERT INTO decisions
                (id, task_id, recommendation, risk, requires_authorization,
                 requires_explicit_acknowledgement, override, capabilities)
            VALUES
                (:id, :task_id, :recommendation, :risk, :requires_authorization,
                 :requires_explicit_acknowledgement, :override, :capabilities)
            ON CONFLICT(id) DO UPDATE SET
                recommendation = excluded.recommendation,
                risk = excluded.risk,
                requires_authorization = excluded.requires_authorization,
                requires_explicit_acknowledgement = excluded.requires_explicit_acknowledgement,
                override = excluded.override,
                capabilities = excluded.capabilities
            """,
            {
                "id": decision.id,
                "task_id": decision.task_id,
                "recommendation": decision.recommendation,
                "risk": decision.risk.value,
                "requires_authorization": int(decision.requires_authorization),
                "requires_explicit_acknowledgement": int(
                    decision.requires_explicit_acknowledgement
                ),
                "override": int(decision.override),
                "capabilities": json.dumps(decision.capabilities),
            },
        )
        self._conn.commit()

    def get_by_task(self, task_id: str) -> Decision | None:
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return Decision(
            id=row["id"],
            task_id=row["task_id"],
            recommendation=row["recommendation"],
            risk=RiskLevel(row["risk"]),
            requires_authorization=bool(row["requires_authorization"]),
            requires_explicit_acknowledgement=bool(
                row["requires_explicit_acknowledgement"]
            ),
            override=bool(row["override"]),
            capabilities=json.loads(row["capabilities"]),
        )