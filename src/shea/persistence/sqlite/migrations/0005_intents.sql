-- 0005_intents: persists parsed Intent records, one per task.

CREATE TABLE IF NOT EXISTS intents (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    type        TEXT NOT NULL,
    goal        TEXT NOT NULL,
    parameters  TEXT NOT NULL DEFAULT '{}',
    confidence  REAL NOT NULL,
    source      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_intents_task_id ON intents(task_id);