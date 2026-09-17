from __future__ import annotations

import subprocess
from typing import Any

from shea.app.adapters.base import Adapter
from shea.app.contracts import AdapterResult, ExecutionAttempt, ExecutionContract, ExecutionReceipt
from shea.app.enums import AppOutcome


class MacOSAdapter(Adapter):
    """Native OS automation adapter for macOS via AppleScript (osascript)."""

    name = "macos_automation"

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.operation.startswith("tool.macos.")

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
            if action == "run_applescript":
                script = args.get("script", "")
                evidence["script"] = script
                
                # Execute native AppleScript
                proc = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=30.0,
                )
                
                evidence["stdout"] = proc.stdout
                evidence["stderr"] = proc.stderr
                
                if proc.returncode == 0:
                    return AdapterResult(
                        outcome=AppOutcome.SUCCESS,
                        evidence=evidence,
                    )
                else:
                    return AdapterResult(
                        outcome=AppOutcome.FAILURE,
                        error=f"AppleScript failed (code {proc.returncode}): {proc.stderr}",
                        evidence=evidence,
                    )
            elif action == "notify":
                title = args.get("title", "Shea Agent")
                message = args.get("message", "")
                
                # Make it safe for applescript injection (basic mitigation)
                safe_title = title.replace('"', '\\"')
                safe_message = message.replace('"', '\\"')
                script = f'display notification "{safe_message}" with title "{safe_title}"'
                
                proc = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                )
                
                if proc.returncode == 0:
                    return AdapterResult(outcome=AppOutcome.SUCCESS, evidence=evidence)
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error="Failed to send notification",
                    evidence=evidence,
                )
            else:
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error=f"Unsupported macos action: {action}",
                    evidence=evidence,
                )
        except subprocess.TimeoutExpired:
            return AdapterResult(
                outcome=AppOutcome.UNKNOWN,
                error="osascript execution timed out",
                evidence=evidence,
            )
        except Exception as e:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"Unexpected error: {e}",
                evidence=evidence,
            )