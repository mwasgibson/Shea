from __future__ import annotations

import sqlite3
from types import TracebackType


class SqliteUnitOfWork:
    """Concrete adapter for the UnitOfWork port (shea.ports.unit_of_work).

    Tracks nesting depth so composed writes commit or roll back together:
    entering increments the depth, exiting decrements it, and only the
    exit that brings the depth back to zero actually calls `commit()` (on
    clean exit) or `rollback()` (on exception). An inner `with` block
    that exits while the depth is still positive does neither — it
    leaves the decision to whichever `with` block is outermost.

    One instance must be shared by every repository/service that needs
    to participate in the same transaction boundary — two separate
    `SqliteUnitOfWork` instances over the same connection would each
    track their own depth and defeat the whole point. Constructor
    parameters are keyword-only and required on the call sites that use
    this (see `Orchestrator`, `SecurityService`, `SqliteTaskRepository`,
    `SqliteAuditSink`) rather than defaulted, so sharing the same
    instance is a visible, explicit fact at every wiring site instead of
    something that can be silently forgotten.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._depth = 0

    def __enter__(self) -> SqliteUnitOfWork:
        self._depth += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        self._depth -= 1
        if self._depth > 0:
            return None
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return None