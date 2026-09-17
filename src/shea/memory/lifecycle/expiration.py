from __future__ import annotations

import sqlite3

from shea.memory.contracts import MemoryStatus
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.ports.clock import Clock


class MemoryLifecycleEnforcer:
    """Handles TTL expiration and hard deletion of memories."""

    def __init__(
        self, 
        conn: sqlite3.Connection, 
        clock: Clock, 
        *, 
        unit_of_work: SqliteUnitOfWork
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._uow = unit_of_work

    def expire_memories(self) -> int:
        """Mark all memories past their expires_at date as EXPIRED.
        
        Returns the number of memories expired.
        """
        now = self._clock.now().isoformat()
        with self._uow:
            cursor = self._conn.execute(
                """
                UPDATE memories 
                SET status = ? 
                WHERE status = ? AND expires_at IS NOT NULL AND expires_at <= ?
                """,
                (MemoryStatus.EXPIRED.value, MemoryStatus.ACTIVE.value, now)
            )
            return cursor.rowcount

    def purge_deleted_memories(self) -> int:
        """Physically remove memories marked as DELETED for privacy compliance.
        
        Returns the number of memories permanently deleted.
        """
        with self._uow:
            cursor = self._conn.execute(
                "DELETE FROM memories WHERE status = ?",
                (MemoryStatus.DELETED.value,)
            )
            return cursor.rowcount