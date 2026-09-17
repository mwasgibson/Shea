from __future__ import annotations

import sqlite3

from shea.memory.ports import VectorStore
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


class FtsVectorStore(VectorStore):
    """BM25 search storage using SQLite FTS5."""

    def __init__(self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork) -> None:
        self._conn = conn
        self._uow = unit_of_work
        
        # Initialize the FTS virtual table
        with self._uow:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts 
                USING fts5(id UNINDEXED, content, profile_id UNINDEXED)
                """
            )

    def upsert(self, memory_id: str, content: str, metadata: dict[str, str]) -> None:
        """Store the memory content in the FTS index."""
        profile_id = metadata.get("profile_id", "")
        with self._uow:
            self._conn.execute("DELETE FROM memory_fts WHERE id = ?", (memory_id,))
            self._conn.execute(
                "INSERT INTO memory_fts (id, content, profile_id) VALUES (?, ?, ?)",
                (memory_id, content, profile_id)
            )

    def search(self, query: str, limit: int = 10, **filters: str) -> list[tuple[str, float]]:
        """Search using BM25 returning (memory_id, score) pairs.
        
        SQLite's BM25 returns smaller (more negative) numbers for better matches.
        We return it as a normalized positive score.
        """
        # Extremely naive escaping for FTS MATCH to prevent syntax errors
        safe_query = "".join(c if c.isalnum() else " " for c in query).strip()
        if not safe_query:
            return []

        # We construct an FTS MATCH query, ORing the terms so we get broad matches
        match_query = " OR ".join(f"{word}*" for word in safe_query.split())

        profile_id = filters.get("profile_id")
        
        if profile_id:
            cursor = self._conn.execute(
                """
                SELECT id, bm25(memory_fts) as score 
                FROM memory_fts 
                WHERE memory_fts MATCH ? AND profile_id = ? 
                ORDER BY score LIMIT ?
                """,
                (match_query, profile_id, limit)
            )
        else:
            cursor = self._conn.execute(
                """
                SELECT id, bm25(memory_fts) as score 
                FROM memory_fts 
                WHERE memory_fts MATCH ? 
                ORDER BY score LIMIT ?
                """,
                (match_query, limit)
            )
            
        scored_results: list[tuple[str, float]] = []
        for row in cursor.fetchall():
            # Flip negative BM25 score to positive
            similarity = abs(row["score"])
            scored_results.append((row["id"], similarity))
            
        return scored_results

    def delete(self, memory_id: str) -> None:
        """Remove the memory from the FTS index."""
        with self._uow:
            self._conn.execute("DELETE FROM memory_fts WHERE id = ?", (memory_id,))