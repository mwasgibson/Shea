from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from shea.contracts.models import Intent


class SqliteIntentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, intent: Intent) -> None:
        self._conn.execute(
            """
            INSERT INTO intents
                (id, task_id, type, goal, parameters, confidence, source, created_at)
            VALUES
                (:id, :task_id, :type, :goal, :parameters, :confidence, :source, :created_at)
            """,
            {
                "id": intent.id,
                "task_id": intent.task_id,
                "type": intent.type,
                "goal": intent.goal,
                "parameters": json.dumps(intent.parameters),
                "confidence": intent.confidence,
                "source": intent.source,
                "created_at": (intent.created_at or datetime.now()).isoformat(),
            },
        )
        self._conn.commit()

    def get_by_task(self, task_id: str) -> Intent | None:
        row = self._conn.execute(
            "SELECT * FROM intents WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return Intent(
            id=row["id"],
            task_id=row["task_id"],
            type=row["type"],
            goal=row["goal"],
            parameters=json.loads(row["parameters"]),
            confidence=row["confidence"],
            source=row["source"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )