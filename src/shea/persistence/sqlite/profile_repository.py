from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from shea.profiles.models import UserProfile

from .unit_of_work import SqliteUnitOfWork


class SqliteProfileRepository:
    """Concrete repository for managing User Profiles in SQLite."""

    def __init__(self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def get(self, profile_id: str) -> UserProfile | None:
        row = self._conn.execute(
            "SELECT * FROM profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_model(row)

    def save(self, profile: UserProfile) -> None:
        now = datetime.now(tz=UTC)
        created = profile.created_at or now

        with self._uow:
            self._conn.execute(
                """
                INSERT INTO profiles (id, name, preferences, context_rules, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    preferences = excluded.preferences,
                    context_rules = excluded.context_rules,
                    updated_at = excluded.updated_at
                """,
                (
                    profile.id,
                    profile.name,
                    json.dumps(profile.preferences),
                    json.dumps(profile.context_rules),
                    created.isoformat(),
                    now.isoformat(),
                ),
            )

    def _row_to_model(self, row: sqlite3.Row) -> UserProfile:
        return UserProfile(
            id=row["id"],
            name=row["name"],
            preferences=json.loads(row["preferences"]),
            context_rules=json.loads(row["context_rules"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_all(self) -> list[UserProfile]:
        rows = self._conn.execute(
            "SELECT * FROM profiles ORDER BY name ASC"
        ).fetchall()
        return [self._row_to_model(row) for row in rows]