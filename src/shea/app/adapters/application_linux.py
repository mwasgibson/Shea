from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from shea.app.adapters.application_policy import (
    desktop_id_allowed,
    executable_allowed,
)
from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.app.ports.process import AdapterContext
from shea.app.scopes import ApplicationScope


class LinuxApplicationAdapter:
    """Phase 6 V1 Linux application control.

    Launch modes (first match):
      - arguments.desktop_id → gtk-launch <id>
      - arguments.path → execve-style subprocess (no shell)
      - arguments.xdg_uri / url target → xdg-open <uri>
      - arguments.name → which(name) then subprocess

    Terminate requires arguments.pid (SIGTERM).
    """

    name = "application.linux"

    def supports(self, contract: ExecutionContract) -> bool:
        if platform.system() != "Linux":
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
                error="application.linux requires scope + AdapterContext",
                evidence=self._base(receipt, attempt),
            )
        app_scope = ctx.scope.application

        op = contract.operation
        if op in {"application.launch", "application.activate"}:
            # activate ≈ launch again on Linux V1 (no portable focus API)
            return self._launch(contract, receipt, attempt, app_scope)
        if op == "application.inspect":
            return self._inspect(contract, receipt, attempt)
        if op == "application.terminate":
            return self._terminate(contract, receipt, attempt, app_scope)
        return AdapterResult(
            outcome=AppOutcome.FAILURE,
            error=f"unsupported operation: {op!r}",
            evidence=self._base(receipt, attempt),
        )

    def _launch(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
        app_scope: ApplicationScope,
    ) -> AdapterResult:
        desktop_id = contract.arguments.get("desktop_id")
        path_arg = contract.arguments.get("path")
        xdg_uri = contract.arguments.get("xdg_uri") or contract.arguments.get("url")
        name_arg = contract.arguments.get("name") or contract.target

        cmd: list[str] | None = None
        mode: str | None = None

        if isinstance(desktop_id, str) and desktop_id.strip():
            if not desktop_id_allowed(desktop_id, app_scope):
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error=f"desktop_id not allowed by application scope allowlist: {desktop_id!r}",
                    evidence=self._base(receipt, attempt),
                )
            if not shutil.which("gtk-launch"):
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error="gtk-launch not available",
                    evidence=self._base(receipt, attempt),
                )
            # desktop id only — no shell metacharacters path
            if "/" in desktop_id or ".." in desktop_id:
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error="desktop_id must be a bare application id",
                    evidence=self._base(receipt, attempt),
                )
            cmd = ["gtk-launch", desktop_id]
            mode = "gtk-launch"

        elif isinstance(path_arg, str) and path_arg.strip():
            if not executable_allowed(path_arg, app_scope):
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error=f"executable not allowed by application scope allowlist: {path_arg!r}",
                    evidence=self._base(receipt, attempt),
                )
            p = Path(path_arg)
            if not p.is_file():
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error=f"executable not found: {path_arg!r}",
                    evidence=self._base(receipt, attempt),
                )
            extra_value = contract.arguments.get("argv_extra", [])
            if extra_value is None:
                extra_value = []
            extra_items = cast(list[object], extra_value)
            if not isinstance(extra_value, list) or not all(
                isinstance(value, str) for value in extra_items
            ):
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error="arguments.argv_extra must be list[str]",
                    evidence=self._base(receipt, attempt),
                )
            extra = [value for value in extra_items if isinstance(value, str)]
            cmd = [str(p.resolve()), *extra]
            mode = "exec"

        elif isinstance(xdg_uri, str) and xdg_uri.strip():
            if not app_scope.allow_xdg_open:
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error="xdg-open is disabled by application scope",
                    evidence=self._base(receipt, attempt),
                )
            if not shutil.which("xdg-open"):
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error="xdg-open not available",
                    evidence=self._base(receipt, attempt),
                )
            cmd = ["xdg-open", xdg_uri]
            mode = "xdg-open"

        elif isinstance(name_arg, str) and name_arg.strip():
            if not executable_allowed(name_arg, app_scope):
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error=f"executable not allowed by application scope allowlist: {name_arg!r}",
                    evidence=self._base(receipt, attempt),
                )
            found = shutil.which(name_arg)
            if not found:
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error=f"executable not on PATH: {name_arg!r}",
                    evidence=self._base(receipt, attempt),
                )
            extra_value = contract.arguments.get("argv_extra", [])
            if extra_value is None:
                extra_value = []
            extra_items = cast(list[object], extra_value)
            if not isinstance(extra_value, list) or not all(
                isinstance(value, str) for value in extra_items
            ):
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error="arguments.argv_extra must be list[str]",
                    evidence=self._base(receipt, attempt),
                )
            extra = [value for value in extra_items if isinstance(value, str)]
            cmd = [found, *extra]
            mode = "path-name"

        else:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="need desktop_id, path, xdg_uri/url, or name/target",
                evidence=self._base(receipt, attempt),
            )

        try:
            proc = subprocess.Popen(  # noqa: S603
                cmd,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence={**self._base(receipt, attempt), "cmd": cmd, "mode": mode},
            )

        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base(receipt, attempt),
                "cmd": cmd,
                "mode": mode,
                "pid": proc.pid,
                "postcondition": "open_accepted",
            },
        )

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
            isinstance(pid_raw, str) and str(pid_raw).isdigit()
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
            os.kill(pid, 15)  # SIGTERM
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

    def _inspect(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        evidence: dict[str, Any] = {
            **self._base(receipt, attempt),
            "platform": platform.platform(),
            "system": platform.system(),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP"),
            "session": os.environ.get("XDG_SESSION_TYPE"),
            "target": contract.target,
            "postcondition": "inspect_platform",
        }
        return AdapterResult(outcome=AppOutcome.SUCCESS, evidence=evidence)

    def _base(
        self, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> dict[str, str]:
        return {"receipt_id": receipt.id, "attempt_id": attempt.id}