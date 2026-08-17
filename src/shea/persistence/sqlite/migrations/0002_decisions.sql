-- 0002_decisions: Decision/Policy/Risk subsystem tables.
-- One task may accumulate multiple authorizations over its lifetime
-- (e.g. re-authorization after RECOVERING), so authorizations is a list
-- keyed by task_id, not a single row. risk_assessments/decisions are kept
-- one-per-task in Phase 2 — extend to history tables if re-assessment
-- becomes a real requirement.

CREATE TABLE IF NOT EXISTS risk_assessments (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    level       TEXT NOT NULL,
    factors     TEXT NOT NULL DEFAULT '[]',  -- JSON array
    explanation TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_risk_assessments_task_id ON risk_assessments(task_id);

CREATE TABLE IF NOT EXISTS decisions (
    id                              TEXT PRIMARY KEY,
    task_id                         TEXT NOT NULL REFERENCES tasks(id),
    recommendation                  TEXT NOT NULL,
    risk                            TEXT NOT NULL,
    requires_authorization          INTEGER NOT NULL,
    requires_explicit_acknowledgement INTEGER NOT NULL DEFAULT 0,
    override                        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_decisions_task_id ON decisions(task_id);

CREATE TABLE IF NOT EXISTS authorizations (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    granted     INTEGER NOT NULL,
    granted_by  TEXT NOT NULL,
    explicit    INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_authorizations_task_id ON authorizations(task_id);