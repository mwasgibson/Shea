from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

from shea.app.adapters.base import Adapter
from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
    effective_requested_target,
)
from shea.app.enums import (
    AppOutcome,
    AttemptState,
    IdempotencyState,
    ReceiptState,
    RecoveryStatus,
)
from shea.app.environment import probe_environment
from shea.app.exceptions import ContractValidationError, ReceiptRequiredError
from shea.app.idempotency import IdempotencyRecord
from shea.app.identity import IdentityResolver, IdentityRevalidator
from shea.app.ports import (
    AppVerificationRepository,
    AttemptRepository,
    EvidenceRepository,
    IdempotencyRepository,
    ReceiptRepository,
    RecoveryRepository,
)
from shea.app.ports.process import AdapterContext
from shea.app.recovery import (
    ReconciliationResult,
    RecoveryIncident,
    classify_stuck_attempt,
)
from shea.app.scope_enforce import evaluate_scope
from shea.app.scopes import ScopeEnforcementReport
from shea.app.verification import AppVerificationRecord, policy_for_operation
from shea.app.verify_engine import evaluate_verification, evidence_from_adapter
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class SupervisionResult:
    receipt: ExecutionReceipt
    attempt: ExecutionAttempt
    adapter_result: AdapterResult
    evidence_id: str | None = None
    verification: AppVerificationRecord | None = None


class ExecutionSupervisor:
    """Sole entry for privileged app-plane work.

    Ordering:
      validate → idempotency reserve → resolve/verify identity → scope →
      persist receipt+attempt → revalidate → INVOKED → invoke adapter →
      evidence + verification → finalize (outcome = verification result)
    No adapter call may precede a durable receipt.
    """

    def __init__(
        self,
        *,
        adapters: list[Adapter],
        receipt_repository: ReceiptRepository,
        attempt_repository: AttemptRepository,
        clock: Clock,
        id_generator: IdGenerator,
        unit_of_work: UnitOfWork,
        identity_resolver: IdentityResolver | None = None,
        identity_revalidator: IdentityRevalidator | None = None,
        evidence_repository: EvidenceRepository | None = None,
        verification_repository: AppVerificationRepository | None = None,
        idempotency_repository: IdempotencyRepository | None = None,
        recovery_repository: RecoveryRepository | None = None,
    ) -> None:
        self._adapters = adapters
        self._receipts = receipt_repository
        self._attempts = attempt_repository
        self._clock = clock
        self._ids = id_generator
        self._uow = unit_of_work
        self._identity_resolver = identity_resolver or IdentityResolver()
        self._identity_revalidator = identity_revalidator or IdentityRevalidator()
        self._evidence_repo = evidence_repository
        self._verification_repo = verification_repository
        self._idempotency_repo = idempotency_repository
        self._recovery_repo = recovery_repository

    def ensure_adapter(self, adapter: Adapter) -> None:
        for index, existing in enumerate(self._adapters):
            if existing.name == adapter.name:
                self._adapters[index] = adapter
                return
        self._adapters.append(adapter)

    def execute(self, contract: ExecutionContract) -> SupervisionResult:
        self._validate(contract)
        adapter = self._select_adapter(contract)

        idem_key = contract.metadata.get("idempotency_key")
        if idem_key is not None:
            self._reserve_idempotency(str(idem_key))

        env = probe_environment(clock_now=self._clock.now())

        requested = effective_requested_target(contract)
        resolved = self._identity_resolver.resolve(
            requested, contract.identity_requirements
        )
        self._identity_revalidator.verify(
            resolved, contract.identity_requirements, phase="pre_receipt"
        )

        enforcement: ScopeEnforcementReport | None = None
        if contract.scope is not None:
            enforcement = evaluate_scope(contract.scope, contract)

        now = self._clock.now()
        receipt = ExecutionReceipt(
            id=self._ids.new_id(),
            contract_id=contract.contract_id,
            authorization_id=contract.authorization_id,
            capability=contract.capability,
            operation=contract.operation,
            target=contract.target,
            state=ReceiptState.CREATED,
            created_at=now,
            adapter_name=adapter.name,
            metadata=dict(contract.metadata),
        )
        attempt = ExecutionAttempt(
            id=self._ids.new_id(),
            receipt_id=receipt.id,
            attempt_number=1,
            state=AttemptState.CREATED,
            created_at=now,
            adapter_name=adapter.name,
        )

        with self._uow:
            self._receipts.save(receipt)
            receipt.state = ReceiptState.ATTEMPTING
            self._receipts.save(receipt)
            self._attempts.save(attempt)
            if idem_key is not None and self._idempotency_repo is not None:
                self._bind_idempotency_receipt(str(idem_key), receipt.id)

        if self._receipts.get(receipt.id) is None:
            raise ReceiptRequiredError(contract.contract_id)

        # Revalidate BEFORE marking INVOKED so a failed check does not
        # leave an attempt stuck in INVOKED with no finalize.
        verified = self._identity_revalidator.verify(
            resolved, contract.identity_requirements, phase="pre_invoke"
        )

        if contract.scope is not None and enforcement is not None:
            ctx = AdapterContext(
                verified_identity=verified,
                scope=contract.scope,
                enforcement=enforcement,
            )
            contract = ExecutionContract(
                contract_id=contract.contract_id,
                authorization_id=contract.authorization_id,
                capability=contract.capability,
                operation=contract.operation,
                target=contract.target,
                arguments=contract.arguments,
                contract_hash=contract.contract_hash,
                expires_at=contract.expires_at,
                requested_target=contract.requested_target,
                identity_requirements=contract.identity_requirements,
                scope=contract.scope,
                metadata={
                    **contract.metadata,
                    "_adapter_context": ctx,
                    "environment": env.platform,
                },
            )

        attempt.state = AttemptState.INVOKED
        attempt.invoked_at = self._clock.now()
        with self._uow:
            self._attempts.save(attempt)

        try:
            result = adapter.invoke(contract, receipt, attempt)
        except Exception as exc:
            # noqa: BLE001 — adapters are untrusted code;
            # anything they raise must still finalize the receipt/attempt
            # rather than leave them dangling in ATTEMPTING/INVOKED forever.
            # Deliberately FAILURE, not UNKNOWN: an exception raised before
            # any external side effect was attempted (argument validation,
            # policy checks, etc. — the common case) means nothing happened,
            # so FAILURE is accurate. An adapter that wants to report a
            # side effect might not have completed should catch its own
            # OSError/TimeoutExpired-style failures internally and return
            # AdapterResult(outcome=UNKNOWN, ...) itself, as
            # LocalProcessAdapter already does for subprocess timeouts.
            result = AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"adapter raised: {exc}",
                evidence={
                    "receipt_id": receipt.id,
                    "attempt_id": attempt.id,
                    "adapter": adapter.name,
                },
            )

        # Phase 4: evidence + independent verification
        policy = policy_for_operation(contract.operation)
        observed_at = self._clock.now()
        evidence = evidence_from_adapter(
            evidence_id=self._ids.new_id(),
            receipt_id=receipt.id,
            attempt_id=attempt.id,
            operation=contract.operation,
            result=result,
            observed_at=observed_at,
        )
        verification = evaluate_verification(
            verification_id=self._ids.new_id(),
            receipt_id=receipt.id,
            attempt_id=attempt.id,
            policy=policy,
            adapter_result=result,
            evidence=evidence,
            verified_at=observed_at,
        )

        final_outcome = verification.result
        if final_outcome is not result.outcome:
            result = AdapterResult(
                outcome=final_outcome,
                evidence=dict(result.evidence),
                error=result.error or verification.explanation,
            )

        attempt.state = AttemptState.FINALIZED
        attempt.finalized_at = self._clock.now()
        attempt.outcome = final_outcome
        attempt.error = result.error
        attempt.evidence = dict(result.evidence)

        receipt.state = ReceiptState.FINALIZED
        receipt.finalized_at = attempt.finalized_at
        receipt.outcome = final_outcome

        with self._uow:
            self._attempts.save(attempt)
            self._receipts.save(receipt)
            if self._evidence_repo is not None:
                self._evidence_repo.save(evidence)
            if self._verification_repo is not None:
                self._verification_repo.save(verification)
            if idem_key is not None:
                self._complete_idempotency(str(idem_key), receipt.id, final_outcome)

        return SupervisionResult(
            receipt=receipt,
            attempt=attempt,
            adapter_result=result,
            evidence_id=evidence.id,
            verification=verification,
        )

    def reconcile_receipt(self, receipt_id: str) -> ReconciliationResult:
        """Finalize stuck receipts without re-invoking adapters (no auto-retry)."""
        receipt = self._receipts.get(receipt_id)
        if receipt is None:
            raise ContractValidationError(f"unknown receipt {receipt_id!r}")

        attempts = self._attempts.list_by_receipt(receipt_id)
        attempt = attempts[-1] if attempts else None
        reason = classify_stuck_attempt(receipt, attempt)
        if reason is None:
            return ReconciliationResult(
                receipt=receipt,
                attempt=attempt,
                incident=None,
                outcome=receipt.outcome or AppOutcome.SUCCESS,
                detail="nothing_to_reconcile",
            )

        # INVOKED without finalize → side effect may have occurred
        outcome = (
            AppOutcome.UNKNOWN
            if reason == "attempt_invoked_not_finalized"
            else AppOutcome.FAILURE
        )
        now = self._clock.now()

        if attempt is not None and attempt.state is not AttemptState.FINALIZED:
            attempt.state = AttemptState.FINALIZED
            attempt.finalized_at = now
            attempt.outcome = outcome
            attempt.error = f"reconciled: {reason}"

        receipt.state = ReceiptState.FINALIZED
        receipt.finalized_at = now
        receipt.outcome = outcome

        incident: RecoveryIncident | None = None
        status = (
            RecoveryStatus.QUARANTINED
            if outcome is AppOutcome.UNKNOWN
            else RecoveryStatus.RESOLVED
        )
        if self._recovery_repo is not None:
            incident = RecoveryIncident(
                id=self._ids.new_id(),
                receipt_id=receipt.id,
                attempt_id=attempt.id if attempt else None,
                status=status,
                reason=reason,
                created_at=now,
                updated_at=now,
                resolution=f"finalized_as_{outcome.value}",
                fence_token=self._ids.new_id(),
            )

        with self._uow:
            if attempt is not None:
                self._attempts.save(attempt)
            self._receipts.save(receipt)
            if incident is not None and self._recovery_repo is not None:
                self._recovery_repo.save_incident(incident)

        return ReconciliationResult(
            receipt=receipt,
            attempt=attempt,
            incident=incident,
            outcome=outcome,
            detail=reason,
        )

    def _reserve_idempotency(self, key: str) -> None:
        if self._idempotency_repo is None:
            return
        existing = self._idempotency_repo.get(key)
        if existing is not None:
            if existing.state is IdempotencyState.COMPLETED:
                raise ContractValidationError(f"idempotency key already completed: {key}")
            if existing.state is IdempotencyState.IN_PROGRESS:
                raise ContractValidationError(f"idempotency key in progress: {key}")
            if existing.state is IdempotencyState.CONFLICT:
                raise ContractValidationError(f"idempotency key conflict: {key}")
        now = self._clock.now()
        record = IdempotencyRecord(
            key=key,
            receipt_id=None,
            state=IdempotencyState.IN_PROGRESS,
            outcome=None,
            created_at=now,
            updated_at=now,
        )
        reserve = getattr(self._idempotency_repo, "reserve", None)
        if reserve is not None:
            try:
                reserve(record)
            except Exception as exc:
                raise ContractValidationError(
                    f"idempotency key already reserved: {key}"
                ) from exc
        else:
            with self._uow:
                self._idempotency_repo.save(record)

    def _bind_idempotency_receipt(self, key: str, receipt_id: str) -> None:
        if self._idempotency_repo is None:
            return
        existing = self._idempotency_repo.get(key)
        now = self._clock.now()
        if existing is None:
            self._idempotency_repo.save(
                IdempotencyRecord(
                    key=key,
                    receipt_id=receipt_id,
                    state=IdempotencyState.IN_PROGRESS,
                    outcome=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            return
        existing.receipt_id = receipt_id
        existing.updated_at = now
        self._idempotency_repo.save(existing)

    def _complete_idempotency(
        self, key: str, receipt_id: str, outcome: AppOutcome
    ) -> None:
        if self._idempotency_repo is None:
            return
        now = self._clock.now()
        state = (
            IdempotencyState.COMPLETED
            if outcome is AppOutcome.SUCCESS
            else IdempotencyState.UNKNOWN
            if outcome is AppOutcome.UNKNOWN
            else IdempotencyState.FAILED
        )
        existing = self._idempotency_repo.get(key)
        created = existing.created_at if existing is not None else now
        self._idempotency_repo.save(
            IdempotencyRecord(
                key=key,
                receipt_id=receipt_id,
                state=state,
                outcome=outcome,
                created_at=created,
                updated_at=now,
            )
        )

    def _validate(self, contract: ExecutionContract) -> None:
        if not contract.contract_id:
            raise ContractValidationError("missing contract_id")
        if not contract.authorization_id:
            raise ContractValidationError("missing authorization_id")
        if not contract.capability:
            raise ContractValidationError("missing capability")
        if not contract.operation:
            raise ContractValidationError("missing operation")
        if not contract.target:
            raise ContractValidationError("missing target")
        if contract.expires_at is not None:
            now = self._clock.now()
            exp = contract.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if now > exp:
                raise ContractValidationError("contract expired")

    def _select_adapter(self, contract: ExecutionContract) -> Adapter:
        for adapter in self._adapters:
            if adapter.supports(contract):
                return adapter
        raise ContractValidationError(
            f"no adapter supports operation {contract.operation!r}"
        )