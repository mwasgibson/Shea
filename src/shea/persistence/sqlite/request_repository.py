from __future__ import annotations

import sqlite3
from datetime import datetime

from shea.contracts.models import Request

from .unit_of_work import SqliteUnitOfWork


class SqliteRequestRepository:
    def __init__(self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork) -> None:
        self._conn = conn
        self._uow = unit_of_work

    def save(self, request: Request) -> None:
        with self._uow:
            self._conn.execute(
                """
                INSERT INTO requests
                (request_id, session_id, actor, input, source,
                created_at, profile_id, response)
                VALUES
                (:request_id, :session_id, :actor, :input, :source,
                :created_at, :profile_id, :response)
                """,
                {
                    "request_id": request.request_id,
                    "session_id": request.session_id,
                    "actor": request.actor,
                    "input": request.input,
                    "source": request.source,
                    "created_at": request.created_at.isoformat(),
                    "profile_id": request.profile_id,
                    "response": request.response,
                },
            )

    def record_response(self, request_id: str, response: str) -> None:
        with self._uow:
            self._conn.execute(
                "UPDATE requests SET response = ? WHERE request_id = ?",
                (response, request_id),
            )

    def get(self, request_id: str) -> Request | None:
        row = self._conn.execute(
            "SELECT * FROM requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_request(row)

    def list_by_session(self, session_id: str) -> list[Request]:
        rows = self._conn.execute(
            "SELECT * FROM requests WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        return [_row_to_request(row) for row in rows]


def _row_to_request(row: sqlite3.Row) -> Request:
    return Request(
        request_id=row["request_id"],
        session_id=row["session_id"],
        actor=row["actor"],
        input=row["input"],
        source=row["source"],
        created_at=datetime.fromisoformat(row["created_at"]),
        profile_id=row["profile_id"],
        response=row["response"],
    )