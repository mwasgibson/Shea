CREATE TABLE IF NOT EXISTS app_evidence (
    id            TEXT PRIMARY KEY,
    receipt_id    TEXT NOT NULL,
    attempt_id    TEXT,
    kind          TEXT NOT NULL,
    source        TEXT NOT NULL,
    strength      TEXT NOT NULL,
    observed_at   TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    payload       TEXT NOT NULL DEFAULT '{}',
    sensitivity   TEXT NOT NULL DEFAULT 'normal',
    FOREIGN KEY (receipt_id) REFERENCES app_receipts(id)
);

CREATE INDEX IF NOT EXISTS idx_app_evidence_receipt ON app_evidence(receipt_id);

CREATE TABLE IF NOT EXISTS app_verifications (
    id                      TEXT PRIMARY KEY,
    receipt_id              TEXT NOT NULL,
    attempt_id              TEXT NOT NULL,
    policy_id               TEXT NOT NULL,
    expected_postconditions TEXT NOT NULL DEFAULT '[]',
    evidence_ids            TEXT NOT NULL DEFAULT '[]',
    result                  TEXT NOT NULL,
    explanation             TEXT NOT NULL,
    verified_at             TEXT NOT NULL,
    FOREIGN KEY (receipt_id) REFERENCES app_receipts(id)
);

CREATE INDEX IF NOT EXISTS idx_app_verifications_receipt ON app_verifications(receipt_id);

CREATE TABLE IF NOT EXISTS app_idempotency (
    key          TEXT PRIMARY KEY,
    receipt_id   TEXT,
    state        TEXT NOT NULL,
    outcome      TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_recovery_incidents (
    id           TEXT PRIMARY KEY,
    receipt_id   TEXT NOT NULL,
    attempt_id   TEXT,
    status       TEXT NOT NULL,
    reason       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    resolution   TEXT,
    fence_token  TEXT,
    metadata     TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_app_recovery_open
    ON app_recovery_incidents(status);