-- 0013_intent_request_ownership: an Intent belongs to a Request
-- (Session -> Request -> Intent), not to a Task. Existing rows are
-- re-pointed at their task's request_id. No FK to requests: historical
-- requests were never persisted before 0012.

CREATE TABLE intents_new (
    id          TEXT PRIMARY KEY,
    request_id  TEXT NOT NULL,
    type        TEXT NOT NULL,
    goal        TEXT NOT NULL,
    parameters  TEXT NOT NULL DEFAULT '{}',
    confidence  REAL NOT NULL,
    source      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

INSERT INTO intents_new (id, request_id, type, goal, parameters, confidence, source, created_at)
SELECT i.id, t.request_id, i.type, i.goal, i.parameters, i.confidence, i.source, i.created_at
FROM intents i
JOIN tasks t ON t.id = i.task_id;

DROP TABLE intents;
ALTER TABLE intents_new RENAME TO intents;

CREATE INDEX idx_intents_request_id ON intents(request_id);