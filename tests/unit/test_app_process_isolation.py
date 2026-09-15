from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime
from typing import cast

from shea.app.adapters.process_local import LocalProcessAdapter
from shea.app.contracts import AdapterResult, ExecutionAttempt, ExecutionContract, ExecutionReceipt
from shea.app.enums import AppOutcome, AttemptState, ReceiptState
from shea.app.exceptions import ContractValidationError
from shea.app.identities import (
    IdentityAssurance,
    IdentityKind,
    ResolvedIdentity,
    VerifiedIdentity,
)
from shea.app.ports.process import AdapterContext
from shea.app.scope_enforce import evaluate_scope
from shea.app.scopes import (
    ExecutionScope,
    IsolationPolicy,
    ProcessScope,
    ResourceLimits,
    ScopeEnforcementReport,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _ctx(scope: ExecutionScope) -> AdapterContext:
    return AdapterContext(
        verified_identity=VerifiedIdentity(
            identity=ResolvedIdentity(
                kind=IdentityKind.PROCESS,
                canonical_value="python",
                requested_value="python",
            ),
            assurance=IdentityAssurance.BASIC,
            verified=True,
            method="test",
        ),
        scope=scope,
        enforcement=ScopeEnforcementReport(
            scope_id=scope.scope_id,
            limits={},
            isolation={},
            filesystem={},
            acceptable=True,
        ),
    )


def _invoke(argv: list[str], scope: ExecutionScope) -> AdapterResult:
    adapter = LocalProcessAdapter()
    contract = ExecutionContract(
        contract_id="c-proc",
        authorization_id="a",
        capability="process.spawn",
        operation="process.spawn",
        target=argv[0],
        arguments={"argv": argv},
        metadata={"_adapter_context": _ctx(scope)},
        scope=scope,
    )
    now = _now()
    receipt = ExecutionReceipt(
        id="r1",
        contract_id="c-proc",
        authorization_id="a",
        capability="process.spawn",
        operation="process.spawn",
        target=argv[0],
        state=ReceiptState.ATTEMPTING,
        created_at=now,
    )
    attempt = ExecutionAttempt(
        id="a1",
        receipt_id="r1",
        attempt_number=1,
        state=AttemptState.INVOKED,
        created_at=now,
        invoked_at=now,
    )
    return adapter.invoke(contract, receipt, attempt)


def test_scope_process_requires_allowlist() -> None:
    scope = ExecutionScope(scope_id="p")
    contract = ExecutionContract(
        contract_id="c",
        authorization_id="a",
        capability="process.spawn",
        operation="process.spawn",
        target="python",
    )
    try:
        evaluate_scope(scope, contract)
        raised = False
    except ContractValidationError as exc:
        raised = True
        assert "process.allowed_executables" in str(exc)
    assert raised


def test_empty_executable_allowlist_denies_spawn() -> None:
    scope = ExecutionScope(
        scope_id="p",
        process=ProcessScope(allowed_executables=frozenset()),
    )
    result = _invoke([sys.executable, "-c", "print(1)"], scope)
    assert result.outcome is AppOutcome.FAILURE
    assert "allowlist" in (result.error or "").lower() or "empty" in (
        result.error or ""
    ).lower()


def test_python_spawn_with_allowlist_and_session() -> None:
    scope = ExecutionScope(
        scope_id="p-ok",
        process=ProcessScope(
            allowed_executables=frozenset({sys.executable, "python", "python3"}),
        ),
        isolation=IsolationPolicy(require_new_session=True),
        resources=ResourceLimits(wall_time_ms=10_000, output_bytes=10_000),
    )
    result = _invoke([sys.executable, "-c", "print('shea-isolation')"], scope)
    assert result.outcome is AppOutcome.SUCCESS
    assert "shea-isolation" in (result.evidence.get("stdout") or "")
    assert result.evidence.get("postcondition") == "process_completed"
    isolation = cast(dict[str, object], result.evidence.get("isolation") or {})
    assert isolation.get("shell") is False
    if platform.system() != "Windows":
        assert isolation.get("new_session") is True or isolation.get(
            "rlimit_attempted"
        )


def test_wall_time_timeout_unknown() -> None:
    scope = ExecutionScope(
        scope_id="p-to",
        process=ProcessScope(
            allowed_executables=frozenset({sys.executable, "python", "python3"}),
        ),
        resources=ResourceLimits(wall_time_ms=200, output_bytes=10_000),
    )
    result = _invoke(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        scope,
    )
    assert result.outcome is AppOutcome.UNKNOWN
    assert "wall_time" in (result.error or "").lower()