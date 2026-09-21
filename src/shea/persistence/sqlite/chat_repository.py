from __future__ import annotations

import json
import sqlite3
from typing import Any

from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


class SqliteChatRepository:
    def __init__(self, conn: sqlite3.Connection, unit_of_work: SqliteUnitOfWork) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save_event(
        self,
        event_id: str,
        session_id: str,
        source: str,
        event_type: str,
        content: str | dict[str, Any],
        created_at: str,
    ) -> None:
        with self._uow:
            content_str = json.dumps(content) if isinstance(content, dict) else content
            self._conn.execute(
                """
                INSERT INTO chat_events (id, session_id, source, event_type, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, session_id, source, event_type, content_str, created_at),
            )

    def get_history(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, source, event_type, content, created_at
            FROM chat_events
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()
        
        history: list[dict[str, Any]] = []
        for row in rows:
            content_str = row["content"]
            try:
                content = json.loads(content_str)
            except json.JSONDecodeError:
                content = content_str
            
            history.append({
                "id": row["id"],
                "source": row["source"],
                "event_type": row["event_type"],
                "content": content,
                "created_at": row["created_at"],
            })
        return history

    def get_all_sessions(self) -> list[dict[str, str]]:
        rows = self._conn.execute(
            """
            SELECT session_id, MAX(created_at) as last_active,
                (SELECT content FROM chat_events c2 
                 WHERE c2.session_id = chat_events.session_id 
                 AND c2.source = 'user' 
                 ORDER BY created_at ASC LIMIT 1) as title
            FROM chat_events
            GROUP BY session_id
            ORDER BY last_active DESC
            LIMIT 100
            """
        ).fetchall()
        
        result: list[dict[str, str]] = []
        for r in rows:
            title_raw = r["title"]
            title = str(title_raw) if title_raw is not None else ""
            if title:
                try:
                    import typing
                    parsed = json.loads(title)
                    if isinstance(parsed, dict):
                        parsed_dict = typing.cast(dict[str, Any], parsed)
                        if "message" in parsed_dict:
                            title = str(parsed_dict["message"])
                        elif "text" in parsed_dict:
                            title = str(parsed_dict["text"])
                        else:
                            title = str(parsed_dict)
                    else:
                        title = str(parsed)
                except Exception:
                    pass
                title = title.strip()
                title = (title[:25] + "...") if len(title) > 25 else title
            else:
                title = str(r["session_id"])[:8]
                
            result.append({
                "session_id": str(r["session_id"]),
                "last_active": str(r["last_active"]),
                "title": title
            })
        return result

    def delete_session(self, session_id: str) -> None:
        with self._uow:
            self._conn.execute(
                """
                DELETE FROM chat_events
                WHERE session_id = ?
                """,
                (session_id,),
            )