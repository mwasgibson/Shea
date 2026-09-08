from __future__ import annotations

import hashlib
import json

from shea.contracts.models import AuditEvent

# Genesis marker for the first event in a chain — an explicit sentinel
# rather than None, so "no previous event" is a stable, hashable value
# instead of a special case every caller has to remember to handle.
GENESIS_PREV_HASH = "0" * 64


def hash_audit_event(event: AuditEvent, prev_hash: str) -> str:
    """Computes the tamper-evident chain hash for one audit event.

    Deliberately hashes the event's own business content — never a raw
    database row — so this stays a pure function any `AuditSink`
    implementation can call, not something coupled to SQLite's column
    layout. `prev_hash` links this event to the one before it: changing,
    reordering, or deleting any earlier event changes what `prev_hash`
    the next event *should* have had, which is what makes tampering
    detectable rather than just theoretically undesirable.

    Same canonicalization approach as
    `shea.recovery.idempotency.IdempotencyKeyGenerator`: sorted keys,
    compact separators, `str()` fallback for anything non-JSON-native —
    reproducible regardless of dict insertion order or which Python
    version produced the event.

    Known limitation, stated plainly rather than oversold: a hash chain
    detects alteration or deletion of any event *before* the current
    chain tip, because it breaks the link the next event depends on. It
    cannot by itself detect truncation of the tail — deleting the most
    recent N events and nothing else leaves a chain that still verifies
    cleanly, because there is nothing after the truncation point to
    notice the gap. Defending against tail truncation needs an external
    anchor (e.g. periodically publishing or externally storing the
    current tip hash) — out of scope here; this function only makes the
    interior of the chain tamper-evident.
    """
    payload = json.dumps(
        {
            "event_id": event.event_id,
            "request_id": event.request_id,
            "task_id": event.task_id,
            "timestamp": event.timestamp.isoformat(),
            "actor": event.actor,
            "component": event.component,
            "event_type": event.event_type,
            "action": event.action,
            "result": event.result,
            "metadata": event.metadata,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()