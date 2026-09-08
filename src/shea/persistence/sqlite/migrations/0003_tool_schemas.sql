-- 0003_tool_schemas: Add table for storing tool argument schemas.
-- This allows schemas to be persisted and loaded dynamically.

CREATE TABLE IF NOT EXISTS tool_schemas (
    tool_name    TEXT PRIMARY KEY,
    schema_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);