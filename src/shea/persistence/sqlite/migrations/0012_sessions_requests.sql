CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,
    actor           TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL,
    last_active_at  TIMESTAMP NOT NULL
);

CREATE TABLE requests (
    request_id  TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    actor       TEXT NOT NULL,
    input       TEXT NOT NULL,
    source      TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL
);

CREATE INDEX idx_requests_session ON requests(session_id, created_at);