CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    preferences TEXT NOT NULL, -- JSON
    context_rules TEXT NOT NULL, -- JSON
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);