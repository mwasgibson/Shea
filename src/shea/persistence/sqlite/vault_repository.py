from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from shea.credentials.contracts import CredentialMetadata
from shea.credentials.ports import VaultRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


class SqliteVaultRepository(VaultRepository):
    """Stores credential metadata and access rules in SQLite.

    Does NOT store the actual secrets.
    """

    def __init__(self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save_metadata(self, metadata: CredentialMetadata) -> None:
        allowed_tools_json = json.dumps(list(metadata.allowed_tools))
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO credentials (
                    id, profile_id, name, description, allowed_tools, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    profile_id = excluded.profile_id,
                    name = excluded.name,
                    description = excluded.description,
                    allowed_tools = excluded.allowed_tools,
                    updated_at = excluded.updated_at
                """,
                (
                    metadata.id,
                    metadata.profile_id,
                    metadata.name,
                    metadata.description,
                    allowed_tools_json,
                    metadata.created_at.isoformat(),
                    metadata.updated_at.isoformat() if metadata.updated_at else None,
                ),
            )

    def _row_to_metadata(self, row: sqlite3.Row) -> CredentialMetadata:
        allowed_tools = frozenset(json.loads(row["allowed_tools"]))
        return CredentialMetadata(
            id=row["id"],
            profile_id=row["profile_id"],
            name=row["name"],
            description=row["description"],
            allowed_tools=allowed_tools,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )

    def get_metadata(self, credential_id: str) -> CredentialMetadata | None:
        cursor = self._conn.execute("SELECT * FROM credentials WHERE id = ?", (credential_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_metadata(row)

    def list_metadata(self) -> list[CredentialMetadata]:
        cursor = self._conn.execute("SELECT * FROM credentials ORDER BY name ASC")
        return [self._row_to_metadata(row) for row in cursor.fetchall()]

    def delete_metadata(self, credential_id: str) -> None:
        with self._uow:
            self._conn.execute("DELETE FROM credentials WHERE id = ?", (credential_id,))

