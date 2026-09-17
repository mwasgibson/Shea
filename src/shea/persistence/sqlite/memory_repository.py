from __future__ import annotations

import sqlite3
from datetime import datetime

from shea.memory.contracts import Memory, MemoryStatus, MemoryType, Sensitivity
from shea.memory.ports import MemoryStore
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


class SqliteMemoryRepository(MemoryStore):
    """Stores structured memories in SQLite.

    Requires ``unit_of_work`` for atomic commits matching the rest of the
    persistence layer.
    """

    def __init__(self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save(self, memory: Memory) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO memories (
                    id, profile_id, type, content, source, provenance,
                    created_at, updated_at, expires_at, confidence,
                    sensitivity, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    content = excluded.content,
                    source = excluded.source,
                    provenance = excluded.provenance,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    confidence = excluded.confidence,
                    sensitivity = excluded.sensitivity,
                    status = excluded.status
                """,
                (
                    memory.id,
                    memory.profile_id,
                    memory.type.value,
                    memory.content,
                    memory.source,
                    memory.provenance,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat() if memory.updated_at else None,
                    memory.expires_at.isoformat() if memory.expires_at else None,
                    memory.confidence,
                    memory.sensitivity.value,
                    memory.status.value,
                ),
            )

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            profile_id=row["profile_id"],
            type=MemoryType(row["type"]),
            content=row["content"],
            source=row["source"],
            provenance=row["provenance"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            confidence=row["confidence"],
            sensitivity=Sensitivity(row["sensitivity"]),
            status=MemoryStatus(row["status"]),
        )

    def get(self, memory_id: str) -> Memory | None:
        cursor = self._conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_memory(row)

    def delete(self, memory_id: str) -> None:
        """Hard delete a memory from the store."""
        with self._uow:
            self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

    def get_active(self, profile_id: str) -> list[Memory]:
        """Return all non-expired, non-deleted memories for a profile."""
        cursor = self._conn.execute(
            "SELECT * FROM memories WHERE profile_id = ? AND status = ? ORDER BY created_at ASC",
            (profile_id, MemoryStatus.ACTIVE.value),
        )
        return [self._row_to_memory(row) for row in cursor.fetchall()]