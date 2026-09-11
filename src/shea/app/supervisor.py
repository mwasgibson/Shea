from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC

from shea.app.adapters.base import Adapter
from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
    effective_requested_target,
)
from shea.app.enums import AppOutcome, AttemptState, ReceiptState
from shea.app.environment import probe_environment
from shea.app.exceptions import ContractValidationError, ReceiptRequiredError
from shea.app.identity import IdentityResolver, IdentityRevalidator
from shea.app.ports import AttemptRepository, ReceiptRepository
from shea.app.ports.process import AdapterContext
from shea.app.scope_enforce import evaluate_scope
from shea.app.scopes import ScopeEnforcementReport
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class SupervisionResult:
    receipt: ExecutionReceipt
    attempt: ExecutionAttempt
    adapter_result: AdapterResult


class ExecutionSupervisor:
    """Sole entry for privileged app-plane work.

    Ordering (non-negotiable):
      validate → resolve/verify identity → evaluate scope →
      persist receipt+attempt → revalidate → invoke adapter → finalize
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
    ) -> None:
        self._adapters = adapters
        self._receipts = receipt_repository
        self._attempts = attempt_repository
        self._clock = clock
        self._ids = id_generator
        self._uow = unit_of_work
        self._identity_resolver = identity_resolver or IdentityResolver()
        self._identity_revalidator = identity_revalidator or IdentityRevalidator()

    def execute(self, contract: ExecutionContract) -> SupervisionResult:
        self._validate(contract)
        adapter = self._select_adapter(contract)

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
            enforcement = evaluate_scope(contract.scope)

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
            contract = replace(
                contract,
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

        attempt.state = AttemptState.FINALIZED
        attempt.finalized_at = self._clock.now()
        attempt.outcome = result.outcome
        attempt.error = result.error
        attempt.evidence = dict(result.evidence)

        receipt.state = ReceiptState.FINALIZED
        receipt.finalized_at = attempt.finalized_at
        receipt.outcome = result.outcome

        with self._uow:
            self._attempts.save(attempt)
            self._receipts.save(receipt)

        return SupervisionResult(
            receipt=receipt, attempt=attempt, adapter_result=result
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