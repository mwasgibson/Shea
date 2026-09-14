from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

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

        body = str(result.evidence.get("body_preview") or "")
        title = self._extract_title(body)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()[:2000]

        evidence: dict[str, Any] = {
            **dict(result.evidence),
            "browser_operation": op,
            "title": title,
            "text_preview": text,
            "postcondition": "page_fetched",
            "browser_mode": "http_document",  # not full browser engine
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