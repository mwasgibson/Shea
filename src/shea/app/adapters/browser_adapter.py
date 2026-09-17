from __future__ import annotations

import webbrowser
from typing import Any

from shea.app.adapters.base import Adapter
from shea.app.contracts import AdapterResult, ExecutionAttempt, ExecutionContract, ExecutionReceipt
from shea.app.enums import AppOutcome


class BrowserAdapter(Adapter):
    """Lightweight browser adapter for native OS browser manipulation."""

    name = "browser_automation"

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.operation.startswith("tool.browser.")

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        action = contract.metadata.get("action")
        args = contract.arguments

        evidence: dict[str, Any] = {
            "receipt_id": receipt.id,
            "attempt_id": attempt.id,
            "adapter": self.name,
            "action": action,
        }

        try:
            if action == "open_url":
                url = args.get("url")
                if not url:
                    return AdapterResult(
                        outcome=AppOutcome.FAILURE,
                        error="Missing 'url' argument",
                        evidence=evidence,
                    )
                    
                evidence["url"] = url
                
                # Native browser launch
                success = webbrowser.open(url)
                
                if success:
                    return AdapterResult(
                        outcome=AppOutcome.SUCCESS,
                        evidence=evidence,
                    )
                else:
                    return AdapterResult(
                        outcome=AppOutcome.FAILURE,
                        error="Failed to open browser (webbrowser.open returned False)",
                        evidence=evidence,
                    )
            else:
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error=f"Unsupported browser action: {action}",
                    evidence=evidence,
                )
        except Exception as e:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"Unexpected error: {e}",
                evidence=evidence,
            )