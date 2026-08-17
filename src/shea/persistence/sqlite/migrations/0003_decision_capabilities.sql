-- 0003_decision_capabilities: record exactly which capabilities a
-- Decision was evaluated and authorized for, so the Execution subsystem
-- can look up "what was actually authorized for this task" from
-- persisted state rather than trusting a value an execution caller
-- happens to pass in.

ALTER TABLE decisions ADD COLUMN capabilities TEXT NOT NULL DEFAULT '[]';