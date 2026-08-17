from __future__ import annotations

from typing import Protocol

from shea.contracts.models import AuditEvent, Authorization, Decision, Plan, RiskAssessment, Task


class TaskRepository(Protocol):
    """Persists Task state — technical doc Section 14: plan/task state is
    persistent, not RAM-only. Any adapter (SQLite today, Postgres later)
    implements this without core/ knowing the difference (Constraint 9).
    """

    def save(self, task: Task) -> None: ...

    def get(self, task_id: str) -> Task | None: ...

    def list_by_session(self, session_id: str) -> list[Task]: ...


class PlanRepository(Protocol):
    """Persists Plan + PlanStep state."""

    def save(self, plan: Plan) -> None: ...

    def get_by_task(self, task_id: str) -> Plan | None: ...


class RiskAssessmentRepository(Protocol):
    """Persists RiskAssessment records — technical doc Section 12."""

    def save(self, risk_assessment: RiskAssessment) -> None: ...

    def get_by_task(self, task_id: str) -> RiskAssessment | None: ...


class DecisionRepository(Protocol):
    """Persists Decision records — technical doc Section 11."""

    def save(self, decision: Decision) -> None: ...

    def get_by_task(self, task_id: str) -> Decision | None: ...


class AuthorizationRepository(Protocol):
    """Persists Authorization records — technical doc Section 11.

    Authorizations are append-only in spirit: a task may accumulate more
    than one over its lifetime (e.g. re-authorization after recovery), so
    this is a list, not a single slot.
    """

    def save(self, authorization: Authorization) -> None: ...

    def list_by_task(self, task_id: str) -> list[Authorization]: ...


class AuditSink(Protocol):
    """Append-only audit event storage — technical doc Section 18.

    Implementations must not mutate or delete existing events; this port
    only exposes `record`, deliberately, to keep that invariant structural
    rather than a matter of discipline.
    """

    def record(self, event: AuditEvent) -> None: ...