-- Migration 0009: Credential Vault
-- Stores metadata (name, description, access scopes) for credentials.
-- Crucially, it does NOT store the secret values, which reside in the OS Keyring.

CREATE TABLE IF NOT EXISTS credentials (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL DEFAULT 'system',
    name TEXT NOT NULL,
    description TEXT,
    allowed_tools TEXT NOT NULL, -- JSON array of allowed tool globs (e.g. '["github.*"]')
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE(profile_id, name)
) STRICT;