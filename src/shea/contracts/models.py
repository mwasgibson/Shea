from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .enums import (
    ExecutionOutcome,
    FailureCategory,
    RecoveryStrategy,
    RiskLevel,
    TaskState,
)

# NOTE on scope: several of these contracts (Intent, Plan, Decision,
# RiskAssessment, Authorization) describe the *shape* that later phases
# (Planning, Decision/Policy, Tools) will populate. Phase 1 only gives
# them behavior-free, storable form so the schema is agreed up front —
# per technical doc Section 8, "Plan state is persistent and is not
# treated as RAM-only runtime information."


@dataclass(frozen=True)
class Request:
    """Technical doc Section 8.1."""

    request_id: str
    session_id: str
    actor: str
    input: str
    source: str
    created_at: datetime


@dataclass(frozen=True)
class Intent:
    """Technical doc Section 8.2."""

    id: str
    task_id: str
    type: str
    goal: str
    parameters: dict[str, Any] = field(default_factory=dict[str, Any])
    confidence: float = 0.0
    source: str = ""
    created_at: datetime | None = None


@dataclass
class PlanStep:
    """One operation within a Plan — technical doc Section 8.3."""

    id: str
    plan_id: str
    order: int
    description: str
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict[str, Any])
    state: str = "PENDING"


@dataclass
class Plan:
    """Technical doc Section 8.3."""

    id: str
    task_id: str
    objective: str
    assumptions: list[str] = field(default_factory=list[str])
    steps: list[PlanStep] = field(default_factory=list[PlanStep])
    risk: RiskLevel | None = None
    result: str | None = None


@dataclass
class RiskAssessment:
    """Technical doc Section 12 — classification + explanation, never just a score."""

    id: str
    task_id: str
    level: RiskLevel
    factors: list[str] = field(default_factory=list[str])
    explanation: str = ""


@dataclass
class Decision:
    """Core authorization/policy decision — technical doc Section 11.

    A Decision is advisory infrastructure, not the authorization itself:
    WARNING != DENIAL (Appendix B). `requires_authorization` says whether
    the user must confirm at all; `requires_explicit_acknowledgement`
    distinguishes the two confirmation tiers from research doc Section
    4.2/9.3 (MEDIUM's "optional acknowledgement" vs HIGH/CRITICAL/UNKNOWN's
    "explicit acknowledgement"). `authorized` is never stored here — what
    actually happened is recorded separately in an Authorization record,
    so a Decision can never retroactively claim an authorization it didn't
    receive.

    `capabilities` records exactly which capabilities this decision was
    evaluated and authorized for, so the Execution subsystem can look up
    "what was actually authorized for this task" from persisted state
    rather than trusting a value an execution caller happens to pass in.
    """

    id: str
    task_id: str
    recommendation: str
    risk: RiskLevel
    requires_authorization: bool
    requires_explicit_acknowledgement: bool = False
    override: bool = False
    capabilities: list[str] = field(default_factory=list[str])


@dataclass
class Authorization:
    """Explicit permission for an operation — technical doc Section 11.

    `explicit` and auditability are both required per Appendix B:
    "USER OVERRIDE = EXPLICIT + AUDITABLE".
    """

    id: str
    task_id: str
    granted: bool
    granted_by: str
    explicit: bool = True


@dataclass
class AuditEvent:
    """Technical doc Section 18 — append-only, correlatable audit record."""

    event_id: str
    request_id: str | None
    task_id: str | None
    timestamp: datetime
    actor: str
    component: str
    event_type: str
    action: str
    result: str
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass
class Task:
    """Unit of work managed by the Orchestrator — technical doc Section 7.2."""

    id: str
    session_id: str
    request_id: str
    state: TaskState
    created_at: datetime
    updated_at: datetime
    plan_id: str | None = None


@dataclass(frozen=True)
class ToolRequest:
    """Technical doc Section 8.4 — every tool invocation follows this
    uniform shape, regardless of which tool is called.
    """

    request_id: str
    tool: str
    action: str
    arguments: dict[str, Any] = field(default_factory=dict[str, Any])
    context: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class ToolResponse:
    """Technical doc Section 8.4 — "Tools return structured errors rather
    than unstructured failures."
    """

    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class ModelResponse:
    """Technical doc Section 8.5's ModelProvider contract — the return
    shape of `generate()`. `structured_data` is populated when the
    provider was asked for (and produced) structured output; callers that
    need JSON must check for None rather than assuming it's always
    present, since a real model can always return prose instead.
    """

    content: str
    structured_data: dict[str, Any] | None = None
    finish_reason: str = "stop"
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass
class ToolExecutionRecord:
    """Persisted record of one tool invocation — technical doc Section
    7.2's "Tool Execution" entity. Kept separate from the audit log so
    VerificationService has something structured to read (`data`, in
    particular) rather than re-parsing audit metadata. `data` must be
    JSON-serializable for records that will be persisted; non-serializable
    values are stored via `str()` as a fallback (see the SQLite adapter).
    """

    id: str
    task_id: str
    tool: str
    action: str
    outcome: ExecutionOutcome
    success: bool
    data: Any = None
    error: str | None = None
    attempt_number: int = 1
    idempotency_key: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

@dataclass
class VerificationRecord:
    """Confirmation that an intended result actually occurred — technical
    doc Section 7.2's "Verification" entity. `verified` is never inferred
    directly from `ToolExecutionRecord.success` by the persistence layer;
    it is whatever a Verifier (shea.verification) decided, which may or
    may not agree with the tool's own report — Appendix B: "EXECUTION
    SUCCESS != VERIFIED SUCCESS".
    """

    id: str
    task_id: str
    verified: bool
    method: str
    explanation: str = ""
    observed_state: Any = None
    expected_state: Any = None
    confidence: float = 1.0
    side_effect_detected: bool = False
    retry_safe: bool = False


@dataclass
class RecoveryAttempt:
    """One attempt to recover a FAILED task — technical doc Section 15's
    Saga-Style Recovery. `resolved`/`recovered` stay unset until
    `RecoveryService.resolve_recovery` runs a Compensator and records what
    it actually found — never optimistically set to True by anything else,
    per Constraint 5: "Rollback must never be claimed successful without
    verification."
    """

    id: str
    task_id: str
    attempt_number: int
    resolved: bool = False
    recovered: bool | None = None
    method: str = ""
    explanation: str = ""
    delay_seconds: float = 0.0
    
@dataclass(frozen=True)
class FailureClassification:
    """Normalized description of an execution failure."""

    category: FailureCategory
    retryable: bool
    recoverable: bool
    reversible: bool
    requires_verification: bool
    security_relevant: bool
    explanation: str = ""


@dataclass(frozen=True)
class RetryPolicy:
    """Rules governing whether and how an execution may be retried."""

    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_backoff: bool = True
    jitter: bool = True
    require_idempotency: bool = True
    reverify_before_retry: bool = True


@dataclass(frozen=True)
class RecoveryDecision:
    """The deterministic strategy selected for a failed operation."""

    strategy: RecoveryStrategy
    reason: str
    requires_verification: bool = False
    requires_user_authorization: bool = False
    safe_to_retry: bool = False


@dataclass(frozen=True)
class VerificationOutcome:
    """Result returned by a tool-specific verifier."""

    verified: bool
    method: str
    explanation: str = ""
    observed_state: Any = None
    expected_state: Any = None
    confidence: float = 1.0
    side_effect_detected: bool = False
    retry_safe: bool = False


@dataclass
class RecoveryCheckpoint:
    """Durable recovery checkpoint for multi-step execution."""

    task_id: str
    plan_id: str | None
    step_id: str | None
    state: str
    last_verified_step: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])    
    
@dataclass
class RecoveryDecisionRecord:
    id: str
    task_id: str
    strategy: RecoveryStrategy
    reason: str
    attempt_number: int
    created_at: datetime