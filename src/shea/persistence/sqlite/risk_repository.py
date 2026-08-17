from __future__ import annotations

import json
import sqlite3

from shea.contracts.enums import RiskLevel
from shea.contracts.models import RiskAssessment


class SqliteRiskAssessmentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, risk_assessment: RiskAssessment) -> None:
        self._conn.execute(
            """
            INSERT INTO risk_assessments (id, task_id, level, factors, explanation)
            VALUES (:id, :task_id, :level, :factors, :explanation)
            ON CONFLICT(id) DO UPDATE SET
                level = excluded.level,
                factors = excluded.factors,
                explanation = excluded.explanation
            """,
            {
                "id": risk_assessment.id,
                "task_id": risk_assessment.task_id,
                "level": risk_assessment.level.value,
                "factors": json.dumps(risk_assessment.factors),
                "explanation": risk_assessment.explanation,
            },
        )
        self._conn.commit()

    def get_by_task(self, task_id: str) -> RiskAssessment | None:
        row = self._conn.execute(
            "SELECT * FROM risk_assessments WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return RiskAssessment(
            id=row["id"],
            task_id=row["task_id"],
            level=RiskLevel(row["level"]),
            factors=json.loads(row["factors"]),
            explanation=row["explanation"],
        )