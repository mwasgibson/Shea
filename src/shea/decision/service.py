from __future__ import annotations

from dataclasses import dataclass

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import PolicyVerdict
from shea.contracts.models import Authorization, Decision, RiskAssessment, Task
from shea.core.orchestrator import Orchestrator
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.repositories import (
    AuthorizationRepository,
    DecisionRepository,
    RiskAssessmentRepository,
)

from .confirmation import confirmation_rule_for
from .exceptions import AuthorizationRequiredError, PolicyDeniedError
from .policy import PolicyEngine
from .risk import RiskEngine, RiskFactors


@dataclass(frozen=True)
class DecisionOutcome:
    """What EvaluateAndAuthorize actually did, for the caller to inspect
    or display. Only returned on success — the two failure paths raise
    instead (see PolicyDeniedError / AuthorizationRequiredError), matching
    the orchestrator's own "raise on illegal transition" pattern.
    """

    decision: Decision
    risk_assessment: RiskAssessment
    authorization: Authorization
    task: Task


class DecisionService:
    """Coordinates the Decision/Policy/Risk pipeline described in
    technical doc Section 11 and research doc Section 4/9.

    This is the ONLY subsystem in Phase 2 that is allowed to call
    `Orchestrator.advance(task_id, "authorize_and_run")`. That is not
    enforced by the type system (Orchestrator is a plain public class),
    but architecturally: nothing else in this codebase should import
    Orchestrator for that purpose. A future phase could tighten this with
    a narrower "Authorizer" port on Orchestrator if that boundary needs to
    be machine-checked rather than a convention.

    Pipeline, matching Section 11's decision pipeline exactly:

        Model Proposal (capabilities a plan wants to use)
              |
              v
        Policy Evaluation  --DENIED-->  PolicyDeniedError (never overridable)
              |
        ALLOWED / REQUIRES_AUTHORIZATION
              |
              v
        Risk Assessment (classification + explanation, Section 12)
              |
              v
        Confirmation tier (Section 4.2) determines whether an explicit
        user acknowledgement is required
              |
              v
        Authorization recorded (explicit or implicit, always audited)
              |
              v
        Orchestrator.advance(task_id, "authorize_and_run")
    """

    def __init__(
        self,
        *,
        policy_engine: PolicyEngine,
        risk_engine: RiskEngine,
        orchestrator: Orchestrator,
        decision_repository: DecisionRepository,
        risk_repository: RiskAssessmentRepository,
        authorization_repository: AuthorizationRepository,
        audit: AuditRecorder,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._policy = policy_engine
        self._risk = risk_engine
        self._orchestrator = orchestrator
        self._decisions = decision_repository
        self._risk_assessments = risk_repository
        self._authorizations = authorization_repository
        self._audit = audit
        self._clock = clock
        self._ids = id_generator

    def evaluate_and_authorize(
        self,
        task: Task,
        *,
        capabilities: frozenset[str],
        reversible: bool = True,
        external_content_involved: bool = False,
        explicit_user_ack: bool = False,
        acting_user: str = "user",
    ) -> DecisionOutcome:
        verdict = self._policy.evaluate(capabilities)

        if verdict is PolicyVerdict.DENIED:
            self._audit.record(
                actor="decision_service",
                component="decision.policy",
                event_type="decision.policy_denied",
                action="evaluate",
                result="denied",
                request_id=task.request_id,
                task_id=task.id,
                metadata={"capabilities": sorted(capabilities)},
            )
            raise PolicyDeniedError(task.id, capabilities & self._policy.deny_capabilities)

        risk_result = self._risk.assess(
            RiskFactors(
                capabilities=capabilities,
                reversible=reversible,
                external_content_involved=external_content_involved,
            )
        )
        risk_assessment = RiskAssessment(
            id=self._ids.new_id(),
            task_id=task.id,
            level=risk_result.level,
            factors=risk_result.factors,
            explanation=risk_result.explanation,
        )
        self._risk_assessments.save(risk_assessment)
        self._audit.record(
            actor="decision_service",
            component="decision.risk",
            event_type="decision.risk_assessed",
            action="assess",
            result="success",
            request_id=task.request_id,
            task_id=task.id,
            metadata={"level": risk_result.level.value, "factors": risk_result.factors},
        )

        rule = confirmation_rule_for(risk_result.level)
        requires_authorization = rule.requires_authorization or (
            verdict is PolicyVerdict.REQUIRES_AUTHORIZATION
        )

        decision = Decision(
            id=self._ids.new_id(),
            task_id=task.id,
            recommendation="proceed" if requires_authorization else "proceed_automatically",
            risk=risk_result.level,
            requires_authorization=requires_authorization,
            requires_explicit_acknowledgement=rule.requires_explicit_acknowledgement,
        )
        self._decisions.save(decision)
        self._audit.record(
            actor="decision_service",
            component="decision.engine",
            event_type="decision.recorded",
            action="decide",
            result="success",
            request_id=task.request_id,
            task_id=task.id,
            metadata={
                "risk": risk_result.level.value,
                "requires_authorization": requires_authorization,
                "requires_explicit_acknowledgement": rule.requires_explicit_acknowledgement,
            },
        )

        authorization = self._resolve_authorization(
            task=task,
            decision=decision,
            risk_assessment=risk_assessment,
            explicit_user_ack=explicit_user_ack,
            acting_user=acting_user,
        )

        updated_task = self._orchestrator.advance(task.id, "authorize_and_run")

        return DecisionOutcome(
            decision=decision,
            risk_assessment=risk_assessment,
            authorization=authorization,
            task=updated_task,
        )

    def _resolve_authorization(
        self,
        *,
        task: Task,
        decision: Decision,
        risk_assessment: RiskAssessment,
        explicit_user_ack: bool,
        acting_user: str,
    ) -> Authorization:
        if not decision.requires_authorization:
            return self._grant(
                task=task,
                granted_by="system",
                explicit=False,
                event_type="decision.authorization.auto",
            )

        if explicit_user_ack:
            return self._grant(
                task=task,
                granted_by=acting_user,
                explicit=True,
                event_type="decision.authorized",
            )

        if not decision.requires_explicit_acknowledgement:
            # MEDIUM tier: "optional acknowledgement" — proceed with an
            # implicit, non-explicit authorization, but the warning is
            # still on record via the Decision + audit trail above.
            return self._grant(
                task=task,
                granted_by="system",
                explicit=False,
                event_type="decision.authorization.implicit",
            )

        # HIGH / CRITICAL / UNKNOWN tier with no explicit ack yet: block.
        self._audit.record(
            actor="decision_service",
            component="decision.authorization",
            event_type="decision.authorization.awaiting",
            action="resolve_authorization",
            result="blocked",
            request_id=task.request_id,
            task_id=task.id,
            metadata={"risk": decision.risk.value},
        )
        raise AuthorizationRequiredError(task.id, decision, risk_assessment)

    def _grant(
        self, *, task: Task, granted_by: str, explicit: bool, event_type: str
    ) -> Authorization:
        authorization = Authorization(
            id=self._ids.new_id(),
            task_id=task.id,
            granted=True,
            granted_by=granted_by,
            explicit=explicit,
        )
        self._authorizations.save(authorization)
        self._audit.record(
            actor=granted_by,
            component="decision.authorization",
            event_type=event_type,
            action="grant",
            result="granted",
            request_id=task.request_id,
            task_id=task.id,
            metadata={"explicit": explicit},
        )
        return authorization