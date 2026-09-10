-- App plane (execution plane): receipts before invoke, attempts per physical call.

CREATE TABLE IF NOT EXISTS app_receipts (
    id                TEXT PRIMARY KEY,
    contract_id       TEXT NOT NULL,
    authorization_id  TEXT NOT NULL,
    capability        TEXT NOT NULL,
    operation         TEXT NOT NULL,
    target            TEXT NOT NULL,
    state             TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    finalized_at      TEXT,
    outcome           TEXT,
    adapter_name      TEXT,
    metadata          TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_app_receipts_contract
    ON app_receipts (contract_id);

CREATE TABLE IF NOT EXISTS app_attempts (
    id              TEXT PRIMARY KEY,
    receipt_id      TEXT NOT NULL,
    attempt_number  INTEGER NOT NULL,
    state           TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    invoked_at      TEXT,
    finalized_at    TEXT,
    outcome         TEXT,
    adapter_name    TEXT,
    error           TEXT,
    evidence        TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (receipt_id) REFERENCES app_receipts(id)
);

CREATE INDEX IF NOT EXISTS idx_app_attempts_receipt
    ON app_attempts (receipt_id);