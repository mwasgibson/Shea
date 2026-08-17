from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def run_migrations(
    conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR
) -> list[str]:
    """Apply any *.sql file in migrations_dir not yet recorded as applied,
    in filename-sorted order (hence the "0001_", "0002_" prefix convention).

    Each migration runs in its own transaction: a failing migration rolls
    back cleanly rather than leaving the schema half-applied, and is not
    recorded as applied, so re-running is safe.
    """
    _ensure_migrations_table(conn)
    already = applied_versions(conn)
    newly_applied: list[str] = []

    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.stem
        if version in already:
            continue

        sql = path.read_text()
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        newly_applied.append(version)

    return newly_applied