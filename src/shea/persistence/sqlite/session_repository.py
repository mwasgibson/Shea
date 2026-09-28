from __future__ import annotations

import sqlite3
from datetime import datetime

from shea.contracts.models import Session
from shea.ports.clock import Clock

from .unit_of_work import SqliteUnitOfWork


class SqliteSessionRepository:
    def __init__(
        self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork, clock: Clock
    ) -> None:
        self._conn = conn
        self._uow = unit_of_work
        self._clock = clock

    def get_or_create(self, session_id: str, *, actor: str) -> Session:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is not None:
            return Session(
                id=row["id"],
                actor=row["actor"],
                created_at=datetime.fromisoformat(row["created_at"]),
                last_active_at=datetime.fromisoformat(row["last_active_at"]),
            )

        now = self._clock.now()
        session = Session(id=session_id, actor=actor, created_at=now, last_active_at=now)
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO sessions (id, actor, created_at, last_active_at)
                VALUES (:id, :actor, :created_at, :last_active_at)
                """,
                {
                    "id": session.id,
                    "actor": session.actor,
                    "created_at": session.created_at.isoformat(),
                    "last_active_at": session.last_active_at.isoformat(),
                },
            )
        return session

    def touch(self, session_id: str) -> None:
        with self._uow:
            self._conn.execute(
                "UPDATE sessions SET last_active_at = ? WHERE id = ?",
                (self._clock.now().isoformat(), session_id),
            )