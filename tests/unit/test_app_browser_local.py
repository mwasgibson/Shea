from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

from shea.app.adapters.browser_local import (
    LocalBrowserAdapter,
    _TitleParser,  # pyright: ignore[reportPrivateUsage]
)
from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
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
    ScopeEnforcementReport,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _verified() -> VerifiedIdentity:
    return VerifiedIdentity(
        identity=ResolvedIdentity(
            kind=IdentityKind.URL,
            canonical_value="https://example.com/",
            requested_value="https://example.com/",
        ),
        assurance=IdentityAssurance.BASIC,
        verified=True,
        method="test",
    )


def _enforcement(scope_id: str = "br") -> ScopeEnforcementReport:
    return ScopeEnforcementReport(
        scope_id=scope_id,
        limits={},
        isolation={},
        filesystem={},
        network={"block_private": EnforcementStatus.ENFORCED},
        application={},
        acceptable=True,
        detail="ok",
    )


def _scope() -> ExecutionScope:
    return ExecutionScope(
        scope_id="br",
        network=NetworkScope(
            allowed_hosts=frozenset({"example.com", "www.example.com"}),
            block_private=True,
        ),
    )


def _ctx(scope: ExecutionScope | None = None) -> AdapterContext:
    scope = scope or _scope()
    return AdapterContext(
        verified_identity=_verified(),
        scope=scope,
        enforcement=_enforcement(scope.scope_id),
    )


def _receipt_attempt(
    *,
    operation: str = "browser.navigate",
    target: str = "https://example.com/",
) -> tuple[ExecutionReceipt, ExecutionAttempt]:
    now = _now()
    receipt = ExecutionReceipt(
        id="r-br-1",
        contract_id="c-br-1",
        authorization_id="auth-1",
        capability="browser.navigate",
        operation=operation,
        target=target,
        state=ReceiptState.ATTEMPTING,
        created_at=now,
        adapter_name="browser.local",
    )
    attempt = ExecutionAttempt(
        id="a-br-1",
        receipt_id=receipt.id,
        attempt_number=1,
        state=AttemptState.INVOKED,
        created_at=now,
        invoked_at=now,
        adapter_name="browser.local",
    )
    return receipt, attempt


def _contract(
    *,
    operation: str = "browser.navigate",
    url: str = "https://example.com/",
    scope: ExecutionScope | None = None,
    with_context: bool = True,
) -> ExecutionContract:
    scope = scope or _scope()
    metadata: dict[str, Any] = {}
    if with_context:
        metadata["_adapter_context"] = _ctx(scope)
    return ExecutionContract(
        contract_id="c-br-1",
        authorization_id="auth-1",
        capability="browser.navigate",
        operation=operation,
        target=url,
        arguments={"url": url, "max_redirects": 2},
        metadata=metadata,
        scope=scope,
    )


def test_supports_browser_operations() -> None:
    adapter = LocalBrowserAdapter()
    assert adapter.supports(_contract(operation="browser.navigate")) is True
    assert adapter.supports(_contract(operation="browser.read")) is True
    other = ExecutionContract(
        contract_id="c",
        authorization_id="a",
        capability="network.request",
        operation="network.request",
        target="x",
    )
    assert adapter.supports(other) is False


def test_requires_adapter_context() -> None:
    adapter = LocalBrowserAdapter()
    contract = _contract(with_context=False)
    receipt, attempt = _receipt_attempt()
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE
    assert "context" in (result.error or "").lower() or "scope" in (
        result.error or ""
    ).lower()


def test_title_parser_extracts_title() -> None:
    parser = _TitleParser()
    parser.feed("<html><head><title> Hello World </title></head></html>")
    assert parser.title.strip() == "Hello World"


def test_extract_title_helper() -> None:
    html = "<html><title>Example Domain</title><body>x</body></html>"
    extract_title = LocalBrowserAdapter._extract_title  # pyright: ignore[reportPrivateUsage]
    assert extract_title(html) == "Example Domain"


def test_navigate_success_via_mocked_network() -> None:
    network = MagicMock()
    network.invoke.return_value = AdapterResult(
        outcome=AppOutcome.SUCCESS,
        evidence={
            "status": 200,
            "_raw_body_preview": "<html><title>Example Domain</title><body>Hi</body></html>",
            "untrusted_content_block": "<UNTRUSTED_DATA>Hi</UNTRUSTED_DATA>",
            "url": "https://example.com/",
            "final_url": "https://example.com/",
            "postcondition": "response_received",
        },
    )
    adapter = LocalBrowserAdapter(network=network)
    contract = _contract(operation="browser.navigate")
    receipt, attempt = _receipt_attempt()
    result = adapter.invoke(contract, receipt, attempt)

    assert result.outcome is AppOutcome.SUCCESS
    assert result.evidence.get("postcondition") == "page_fetched"
    assert result.evidence.get("browser_mode") == "http_document"
    assert result.evidence.get("title") == "Example Domain"
    assert "Hi" in (result.evidence.get("untrusted_content_block") or "")
    network.invoke.assert_called_once()
    net_contract = network.invoke.call_args[0][0]
    assert net_contract.operation == "network.request"
    assert net_contract.arguments["url"] == "https://example.com/"


def test_read_propagates_network_failure() -> None:
    network = MagicMock()
    network.invoke.return_value = AdapterResult(
        outcome=AppOutcome.FAILURE,
        error="blocked private host",
        evidence={"url": "http://127.0.0.1/"},
    )
    adapter = LocalBrowserAdapter(network=network)
    scope = ExecutionScope(
        scope_id="br",
        network=NetworkScope(block_private=True),
    )
    contract = _contract(
        operation="browser.read",
        url="http://127.0.0.1/",
        scope=scope,
    )
    receipt, attempt = _receipt_attempt(
        operation="browser.read", target="http://127.0.0.1/"
    )
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE
    assert "blocked" in (result.error or "").lower() or result.error


def test_localhost_via_real_network_adapter_fails() -> None:
    """Uses real LocalNetworkAdapter SSRF checks (no live internet)."""
    adapter = LocalBrowserAdapter()
    scope = ExecutionScope(
        scope_id="br-local",
        network=NetworkScope(allowed_hosts=None, block_private=True),
    )
    contract = _contract(
        operation="browser.navigate",
        url="http://127.0.0.1/",
        scope=scope,
    )
    receipt, attempt = _receipt_attempt(target="http://127.0.0.1/")
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE