from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from shea.audit.chain import GENESIS_PREV_HASH, hash_audit_event
from shea.contracts.models import AuditEvent


@dataclass(frozen=True)
class AuditChainBreak:
    """One detected inconsistency in the chain, at a specific sequence
    number, described in plain terms rather than just "hash mismatch" —
    the three cases below want different remediation.
    """

    sequence_number: int
    kind: str  # "content_altered" | "link_broken" | "sequence_gap"
    detail: str


@dataclass(frozen=True)
class AuditChainVerificationResult:
    valid: bool
    events_checked: int
    breaks: tuple[AuditChainBreak, ...]


def verify_audit_chain(conn: sqlite3.Connection) -> AuditChainVerificationResult:
    """Replays the audit_events hash chain from the database and checks
    it against itself.

    For every stored row, in sequence order: recompute what its
    `event_hash` should be from its own stored content plus the
    previous row's stored `event_hash`, using the exact same pure
    function (`hash_audit_event`) that produced it at write time. A
    mismatch there means the row's content was altered after being
    written (`content_altered`) — the row itself no longer hashes to
    what it claims. A stored `prev_hash` that doesn't match the actual
    previous row's `event_hash` means some row between them was
    replaced, reordered, or removed and something was patched in to
    hide it (`link_broken`) — or, more simply, that a row was deleted
    from the middle and nothing downstream was recomputed to match
    (`sequence_gap`, checked independently via the sequence_number
    column so a deletion is caught even in the edge case where a
    coincidental hash collision would not be, astronomically unlikely as
    that is).

    Does NOT detect truncation of the tail (deleting the most recent N
    events and nothing else) — see `hash_audit_event`'s docstring for
    why that is a structural limitation of hash chains, not something
    this function forgot to check.
    """
    rows = conn.execute("SELECT * FROM audit_events ORDER BY sequence_number ASC").fetchall()

    breaks: list[AuditChainBreak] = []
    expected_prev_hash = GENESIS_PREV_HASH
    expected_sequence_number = 1

    for row in rows:
        sequence_number = row["sequence_number"]

        if sequence_number != expected_sequence_number:
            breaks.append(
                AuditChainBreak(
                    sequence_number=expected_sequence_number,
                    kind="sequence_gap",
                    detail=(
                        f"expected sequence_number {expected_sequence_number}, "
                        f"found {sequence_number} — an event was deleted or "
                        "the sequence was tampered with"
                    ),
                )
            )
            # Resynchronize to what's actually present so a single gap
            # doesn't cascade into a false "everything after this is
            # also broken" report.
            expected_sequence_number = sequence_number

        if row["prev_hash"] != expected_prev_hash:
            breaks.append(
                AuditChainBreak(
                    sequence_number=sequence_number,
                    kind="link_broken",
                    detail=(
                        f"stored prev_hash {row['prev_hash']!r} does not match the "
                        f"previous event's actual hash {expected_prev_hash!r}"
                    ),
                )
            )

        event = AuditEvent(
            event_id=row["event_id"],
            request_id=row["request_id"],
            task_id=row["task_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            actor=row["actor"],
            component=row["component"],
            event_type=row["event_type"],
            action=row["action"],
            result=row["result"],
            metadata=json.loads(row["metadata"]),
        )
        recomputed_hash = hash_audit_event(event, row["prev_hash"])
        if recomputed_hash != row["event_hash"]:
            breaks.append(
                AuditChainBreak(
                    sequence_number=sequence_number,
                    kind="content_altered",
                    detail=(
                        f"stored event_hash {row['event_hash']!r} does not match "
                        f"the hash recomputed from this row's own content "
                        f"({recomputed_hash!r}) — this row was modified after "
                        "being written"
                    ),
                )
            )

        expected_prev_hash = row["event_hash"]
        expected_sequence_number = sequence_number + 1

    return AuditChainVerificationResult(
        valid=len(breaks) == 0,
        events_checked=len(rows),
        breaks=tuple(breaks),
    )