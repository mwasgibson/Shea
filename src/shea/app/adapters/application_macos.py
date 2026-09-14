from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any

from shea.app.adapters.application_policy import app_name_allowed, bundle_id_allowed
from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.app.ports.process import AdapterContext
from shea.app.scopes import ApplicationScope


class MacOSApplicationAdapter:
    """Phase 6 V1 macOS application control via `open` / limited inspect.

    Not full Accessibility/TCC automation — launch by bundle id or name only.
    Requires scope + AdapterContext (same fail-closed pattern as process/FS).
    """

    name = "application.macos"

    def supports(self, contract: ExecutionContract) -> bool:
        if platform.system() != "Darwin":
            return False
        return contract.operation.startswith("application.") or contract.capability in {
            "application.launch",
            "application.activate",
            "application.terminate",
            "application.inspect",
        }

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        raw_ctx = contract.metadata.get("_adapter_context")
        ctx: AdapterContext | None = (
            raw_ctx if isinstance(raw_ctx, AdapterContext) else None
        )
        if ctx is None:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="application.macos requires scope + AdapterContext",
                evidence=self._base(receipt, attempt),
            )
        app_scope = ctx.scope.application

        op = contract.operation
        if op in {"application.launch", "application.activate"}:
            return self._launch_or_activate(
                contract,
                receipt,
                attempt,
                app_scope,
                activate=op.endswith("activate"),
            )
        if op == "application.inspect":
            return self._inspect(contract, receipt, attempt)
        if op == "application.terminate":
            return self._terminate(contract, receipt, attempt, app_scope)
        return AdapterResult(
            outcome=AppOutcome.FAILURE,
            error=f"unsupported operation: {op!r}",
            evidence=self._base(receipt, attempt),
        )

    def _launch_or_activate(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
        app_scope: ApplicationScope,
        *,
        activate: bool,
    ) -> AdapterResult:
        bundle_id = contract.arguments.get("bundle_id")
        app_name = contract.arguments.get("name") or contract.target
        if not isinstance(bundle_id, str) and not isinstance(app_name, str):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="need arguments.bundle_id or arguments.name/target",
                evidence=self._base(receipt, attempt),
            )
        if isinstance(bundle_id, str) and bundle_id:
            if not bundle_id_allowed(bundle_id, app_scope):
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error=f"bundle_id not allowed by application scope allowlist: {bundle_id!r}",
                    evidence=self._base(receipt, attempt),
                )
        elif isinstance(app_name, str) and not app_name_allowed(app_name, app_scope):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"application name not allowed by application scope allowlist: {app_name!r}",
                evidence=self._base(receipt, attempt),
            )

        if not shutil.which("open"):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="'open' not available",
                evidence=self._base(receipt, attempt),
            )

        cmd: list[str] = ["open"]
        if activate:
            cmd.append("-a")
        if isinstance(bundle_id, str) and bundle_id:
            # open -b bundle.id
            cmd.extend(["-b", bundle_id])
        else:
            cmd.extend(["-a", str(app_name)])

        try:
            completed = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                timeout=15,
                check=False,
            )
        except OSError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence=self._base(receipt, attempt),
            )
        except subprocess.TimeoutExpired:
            return AdapterResult(
                outcome=AppOutcome.UNKNOWN,
                error="open timed out",
                evidence=self._base(receipt, attempt),
            )

        if completed.returncode != 0:
            err = completed.stderr.decode("utf-8", errors="replace")
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=err or f"open exit {completed.returncode}",
                evidence={
                    **self._base(receipt, attempt),
                    "cmd": cmd,
                    "returncode": completed.returncode,
                },
            )
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base(receipt, attempt),
                "cmd": cmd,
                "bundle_id": bundle_id,
                "name": app_name,
                "activated": activate,
                "postcondition": "open_accepted",
            },
        )

    def _inspect(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        # V1: report platform only; richer AX/process listing is later
        evidence: dict[str, Any] = {
            **self._base(receipt, attempt),
            "platform": platform.platform(),
            "system": platform.system(),
            "target": contract.target,
            "postcondition": "inspect_platform",
        }
        return AdapterResult(outcome=AppOutcome.SUCCESS, evidence=evidence)

    def _terminate(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
        app_scope: ApplicationScope,
    ) -> AdapterResult:
        if not app_scope.allow_terminate:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="application terminate is disabled by application scope",
                evidence=self._base(receipt, attempt),
            )
        pid_raw = contract.arguments.get("pid")
        if not isinstance(pid_raw, int) and not (
            isinstance(pid_raw, str) and pid_raw.isdigit()
        ):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="application.terminate requires arguments.pid (int)",
                evidence=self._base(receipt, attempt),
            )
        pid = int(pid_raw)
        if pid <= 1:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="refusing to signal pid <= 1",
                evidence=self._base(receipt, attempt),
            )
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            return AdapterResult(
                outcome=AppOutcome.SUCCESS,
                evidence={
                    **self._base(receipt, attempt),
                    "pid": pid,
                    "note": "already absent",
                    "postcondition": "terminate_requested",
                },
            )
        except PermissionError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence={**self._base(receipt, attempt), "pid": pid},
            )
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base(receipt, attempt),
                "pid": pid,
                "signal": "SIGTERM",
                "postcondition": "terminate_requested",
            },
        )
    def _base(
        self, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> dict[str, str]:
        return {"receipt_id": receipt.id, "attempt_id": attempt.id}