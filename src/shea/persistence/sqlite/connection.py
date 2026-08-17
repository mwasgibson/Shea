from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


def open_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with the pragmas Shea relies on.

    - row_factory=Row: repositories address columns by name, not position.
    - foreign_keys=ON: SQLite disables FK enforcement by default; this
      makes the plan_steps -> plans -> tasks references in the schema
      actually mean something.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection_scope(db_path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    conn = open_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()