-- 0001_initial: Phase 1 schema — tasks, plans, plan_steps, audit_events.
-- Plan/task state is the authoritative source of truth (technical doc
-- Section 14); the runtime may cache in-memory but must not treat that
-- cache as authoritative.

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    request_id  TEXT NOT NULL,
    state       TEXT NOT NULL,
    plan_id     TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_session_id ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);

CREATE TABLE IF NOT EXISTS plans (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    objective   TEXT NOT NULL,
    assumptions TEXT NOT NULL DEFAULT '[]',  -- JSON array
    risk        TEXT,
    result      TEXT
);

CREATE INDEX IF NOT EXISTS idx_plans_task_id ON plans(task_id);

CREATE TABLE IF NOT EXISTS plan_steps (
    id          TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL REFERENCES plans(id),
    step_order  INTEGER NOT NULL,
    description TEXT NOT NULL,
    tool        TEXT,
    arguments   TEXT NOT NULL DEFAULT '{}',  -- JSON object
    state       TEXT NOT NULL DEFAULT 'PENDING'
);

CREATE INDEX IF NOT EXISTS idx_plan_steps_plan_id ON plan_steps(plan_id);

-- Audit is append-only by convention here; the AuditSink port only
-- exposes `record`, so nothing in this codebase issues UPDATE/DELETE
-- against this table.
CREATE TABLE IF NOT EXISTS audit_events (
    event_id    TEXT PRIMARY KEY,
    request_id  TEXT,
    task_id     TEXT,
    timestamp   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    component   TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    action      TEXT NOT NULL,
    result      TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}'  -- JSON object
);

CREATE INDEX IF NOT EXISTS idx_audit_events_task_id ON audit_events(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_request_id ON audit_events(request_id);