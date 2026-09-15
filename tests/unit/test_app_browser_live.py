from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from shea.app.adapters.browser_local import LocalBrowserAdapter
from shea.app.contracts import ExecutionAttempt, ExecutionContract, ExecutionReceipt
from shea.app.enums import AppOutcome, AttemptState, ReceiptState
from shea.app.identities import (
    IdentityAssurance,
    IdentityKind,
    ResolvedIdentity,
    VerifiedIdentity,
)
from shea.app.ports.process import AdapterContext
from shea.app.scopes import (
    EnforcementStatus,
    ExecutionScope,
    NetworkScope,
    ResourceLimits,
    ScopeEnforcementReport,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("SHEA_LIVE_NETWORK") != "1",
    reason="Set SHEA_LIVE_NETWORK=1 to run live browser.local fetch",
)


def test_live_browser_navigate_example_com() -> None:
    now = datetime.now(UTC)
    scope = ExecutionScope(
        scope_id="br-live",
        network=NetworkScope(
            allowed_hosts=frozenset({"example.com", "www.example.com"}),
            block_private=True,
        ),
        resources=ResourceLimits(wall_time_ms=15_000, output_bytes=500_000),
    )
    ctx = AdapterContext(
        verified_identity=VerifiedIdentity(
            identity=ResolvedIdentity(
                kind=IdentityKind.URL,
                canonical_value="https://example.com/",
                requested_value="https://example.com/",
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
            network={"allowed_hosts": EnforcementStatus.ENFORCED},
            application={},
            acceptable=True,
        ),
    )
    contract = ExecutionContract(
        contract_id="c-live-br",
        authorization_id="auth-live",
        capability="browser.navigate",
        operation="browser.navigate",
        target="https://example.com/",
        arguments={"url": "https://example.com/", "max_redirects": 3},
        metadata={"_adapter_context": ctx},
        scope=scope,
    )
    receipt = ExecutionReceipt(
        id="r-live-br",
        contract_id=contract.contract_id,
        authorization_id=contract.authorization_id,
        capability=contract.capability,
        operation=contract.operation,
        target=contract.target,
        state=ReceiptState.ATTEMPTING,
        created_at=now,
    )
    attempt = ExecutionAttempt(
        id="a-live-br",
        receipt_id=receipt.id,
        attempt_number=1,
        state=AttemptState.INVOKED,
        created_at=now,
        invoked_at=now,
    )

    result = LocalBrowserAdapter().invoke(contract, receipt, attempt)

    assert result.outcome is AppOutcome.SUCCESS
    assert result.evidence.get("postcondition") == "page_fetched"
    assert result.evidence.get("status") == 200
    title = (result.evidence.get("title") or "").lower()
    assert "example" in title or "example" in (
        result.evidence.get("text_preview") or ""
    ).lower()