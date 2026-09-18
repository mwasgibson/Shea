from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from shea.app.adapters.browser_profiles import plan_browser_launch
from shea.app.adapters.network_local import LocalNetworkAdapter
from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.app.ports.process import AdapterContext


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


class LocalBrowserAdapter:
    """EP Phase 5/depth V1 browser port: navigate + read via supervised HTTP.

    Not full browser automation (no JS DOM, no isolated profile yet).
    Side effects go through network.local checks (DNS pin, private block).
    """

    name = "browser.local"

    def __init__(self, network: LocalNetworkAdapter | None = None) -> None:
        self._network = network or LocalNetworkAdapter()

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.operation.startswith("browser.") or contract.capability in {
            "browser.navigate",
            "browser.read",
        }

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        raw_ctx = contract.metadata.get("_adapter_context")
        if not isinstance(raw_ctx, AdapterContext):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="browser.local requires scope + AdapterContext",
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )

        browser_scope = raw_ctx.scope.browser
        plan = plan_browser_launch(browser_scope)
        if not plan.ephemeral:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=(
                    "browser.local supports only EPHEMERAL_ISOLATED profile mode; "
                    "use browser.engine for persistent profiles"
                ),
                evidence=self._base(receipt, attempt),
            )

        op = contract.operation
        if op not in {"browser.navigate", "browser.read"} and not op.startswith(
            "browser."
        ):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"unsupported browser operation: {op!r}",
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )

        # Reuse network.request semantics
        net_contract = ExecutionContract(
            contract_id=contract.contract_id,
            authorization_id=contract.authorization_id,
            capability="network.request",
            operation="network.request",
            target=contract.target,
            arguments={
                "url": contract.arguments.get("url") or contract.target,
                "method": "GET",
                "max_redirects": int(contract.arguments.get("max_redirects", 3)),
            },
            metadata=dict(contract.metadata),
            scope=contract.scope,
            requested_target=contract.requested_target,
            identity_requirements=contract.identity_requirements,
            expires_at=contract.expires_at,
        )
        result = self._network.invoke(net_contract, receipt, attempt)
        if result.outcome is not AppOutcome.SUCCESS:
            return result

        body = str(result.evidence.get("_raw_body_preview") or "")
        identities = result.evidence.get("destination_identity_chain", [])
        title = self._extract_title(body)
        
        # Remove _raw_body_preview from result evidence so it isn't forwarded
        forwarded_evidence = dict(result.evidence)
        forwarded_evidence.pop("_raw_body_preview", None)

        evidence: dict[str, Any] = {
            **forwarded_evidence,
            "browser_operation": op,
            "title": title,
            "postcondition": "page_fetched",
            "browser_mode": "http_document",  # not full browser engine
            "destination_identity_chain": identities,
            "content_trust": browser_scope.content_trust,
            "business_success": None,
            "profile_mode": plan.mode.value,
            "ephemeral": plan.ephemeral,
        }
        return AdapterResult(outcome=AppOutcome.SUCCESS, evidence=evidence)

    @staticmethod
    def _extract_title(html: str) -> str:
        parser = _TitleParser()
        try:
            parser.feed(html)
        except Exception:
            return ""
        return parser.title.strip()[:500]

    @staticmethod
    def _base(
        receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> dict[str, str]:
        return {"receipt_id": receipt.id, "attempt_id": attempt.id}