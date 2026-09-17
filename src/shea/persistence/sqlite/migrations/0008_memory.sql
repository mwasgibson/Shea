-- Migration 0008: Memory Subsystem
-- Creates the table for storing durable, structured memory metadata and content.

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    expires_at TEXT,
    confidence REAL NOT NULL,
    sensitivity TEXT NOT NULL,
    status TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_memories_profile_status ON memories(profile_id, status);
CREATE INDEX IF NOT EXISTS idx_memories_expires_at ON memories(expires_at) WHERE expires_at IS NOT NULL;