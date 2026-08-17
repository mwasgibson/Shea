from __future__ import annotations

import sqlite3

from shea.contracts.models import Authorization


class SqliteAuthorizationRepository:
    """Authorizations are insert-only and listed, never upserted — a task
    can legitimately accumulate more than one over its lifetime (e.g.
    re-authorization after recovery), and each is its own audit-relevant
    fact per Appendix B: "USER OVERRIDE = EXPLICIT + AUDITABLE".
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, authorization: Authorization) -> None:
        self._conn.execute(
            """
            INSERT INTO authorizations (id, task_id, granted, granted_by, explicit)
            VALUES (:id, :task_id, :granted, :granted_by, :explicit)
            """,
            {
                "id": authorization.id,
                "task_id": authorization.task_id,
                "granted": int(authorization.granted),
                "granted_by": authorization.granted_by,
                "explicit": int(authorization.explicit),
            },
        )
        self._conn.commit()

    def list_by_task(self, task_id: str) -> list[Authorization]:
        rows = self._conn.execute(
            "SELECT * FROM authorizations WHERE task_id = ? ORDER BY rowid",
            (task_id,),
        ).fetchall()
        return [
            Authorization(
                id=row["id"],
                task_id=row["task_id"],
                granted=bool(row["granted"]),
                granted_by=row["granted_by"],
                explicit=bool(row["explicit"]),
            )
            for row in rows
        ]