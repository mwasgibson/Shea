-- 0004_verification_recovery: Verification & Recovery subsystem tables.
-- All three are append-only-in-spirit and listed by task_id (like
-- authorizations), since a task may accumulate more than one of each
-- across retries.

CREATE TABLE IF NOT EXISTS tool_executions (
    id      TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    tool    TEXT NOT NULL,
    action  TEXT NOT NULL,
    outcome TEXT NOT NULL,
    success INTEGER NOT NULL,
    data    TEXT,
    error   TEXT,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT,
    started_at TEXT,
    finished_at TEXT,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_executions_task_id ON tool_executions(task_id);
CREATE INDEX IF NOT EXISTS idx_tool_executions_idempotency_key ON tool_executions(idempotency_key);

CREATE TABLE IF NOT EXISTS verifications (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    verified    INTEGER NOT NULL,
    method      TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    observed_state   TEXT,
    expected_state   TEXT,
    confidence       REAL NOT NULL DEFAULT 1.0,
    side_effect_detected  INTEGER NOT NULL DEFAULT 0,
    retry_safe INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_verifications_task_id ON verifications(task_id);

CREATE TABLE IF NOT EXISTS recovery_attempts (
    id             TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL REFERENCES tasks(id),
    attempt_number INTEGER NOT NULL,
    resolved       INTEGER NOT NULL DEFAULT 0,
    recovered      INTEGER,
    method         TEXT NOT NULL DEFAULT '',
    explanation    TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_recovery_attempts_task_id ON recovery_attempts(task_id);