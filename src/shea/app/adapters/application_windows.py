from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from shea.app.adapters.application_policy import executable_allowed
from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.app.ports.process import AdapterContext
from shea.app.scopes import ApplicationScope


class WindowsApplicationAdapter:
    """Phase 6 V1 Windows application control.

    Launch by executable path (preferred) or resolved name on PATH.
    Uses CreateProcess-style subprocess (no shell). Activate is best-effort
    Start-Process. Terminate requires explicit pid argument.
    """

    name = "application.windows"

    def supports(self, contract: ExecutionContract) -> bool:
        if platform.system() != "Windows":
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
                error="application.windows requires scope + AdapterContext",
                evidence=self._base(receipt, attempt),
            )
        app_scope = ctx.scope.application

        op = contract.operation
        if op in {"application.launch", "application.activate"}:
            return self._launch(
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

    def _resolve_executable(
        self, contract: ExecutionContract, app_scope: ApplicationScope
    ) -> tuple[str | None, str | None]:
        """Return (path, error)."""
        path_arg = contract.arguments.get("path")
        name_arg = contract.arguments.get("name") or contract.target

        if isinstance(path_arg, str) and path_arg.strip():
            if not executable_allowed(path_arg, app_scope):
                return None, f"executable not allowed by application scope allowlist: {path_arg!r}"
            p = Path(path_arg)
            if not p.is_file():
                return None, f"executable not found: {path_arg!r}"
            return str(p.resolve()), None

        if isinstance(name_arg, str) and name_arg.strip():
            if not executable_allowed(name_arg, app_scope):
                return None, f"executable not allowed by application scope allowlist: {name_arg!r}"
            found = shutil.which(name_arg)
            if found:
                return found, None
            # Common: name without .exe
            found = shutil.which(f"{name_arg}.exe")
            if found:
                return found, None
            return None, f"executable not on PATH: {name_arg!r}"

        return None, "need arguments.path or arguments.name/target"

    def _launch(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
        app_scope: ApplicationScope,
        *,
        activate: bool,
    ) -> AdapterResult:
        exe, err = self._resolve_executable(contract, app_scope)
        if err or not exe:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=err or "missing executable",
                evidence=self._base(receipt, attempt),
            )

        # Optional extra args (list[str] only)
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
        cmd: list[str] = [exe, *extra]

        try:
            # DETACHED_PROCESS / CREATE_NEW_PROCESS_GROUP when available
            creationflags: int = 0
            if hasattr(subprocess, "DETACHED_PROCESS"):
                creationflags |= int(subprocess.DETACHED_PROCESS)  # type: ignore[attr-defined]
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creationflags |= int(subprocess.CREATE_NEW_PROCESS_GROUP)  # type: ignore[attr-defined]

            proc = subprocess.Popen(  # noqa: S603
                cmd,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
        except OSError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence={**self._base(receipt, attempt), "cmd": cmd},
            )

        # Best-effort activate: Start-Process -WindowStyle Normal (no shell script injection)
        if activate:
            try:
                subprocess.run(  # noqa: S603
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        "Start-Process",
                        "-FilePath",
                        exe,
                    ],
                    capture_output=True,
                    timeout=15,
                    check=False,
                    shell=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass  # launch already succeeded

        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base(receipt, attempt),
                "cmd": cmd,
                "pid": proc.pid,
                "path": exe,
                "activated": activate,
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
        if pid <= 0:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="invalid pid",
                evidence=self._base(receipt, attempt),
            )
        if not app_scope.allow_terminate:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="application terminate is disabled by application scope",
                evidence=self._base(receipt, attempt),
            )
        if not app_scope.allow_terminate:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="application termination is disabled by application scope",
                evidence=self._base(receipt, attempt),
            )

        try:
            completed = subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(pid), "/T"],
                capture_output=True,
                timeout=15,
                check=False,
                shell=False,
            )
        except OSError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence={**self._base(receipt, attempt), "pid": pid},
            )
        except subprocess.TimeoutExpired:
            return AdapterResult(
                outcome=AppOutcome.UNKNOWN,
                error="taskkill timed out",
                evidence={**self._base(receipt, attempt), "pid": pid},
            )

        if completed.returncode != 0:
            err = completed.stderr.decode("utf-8", errors="replace")
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=err or f"taskkill exit {completed.returncode}",
                evidence={**self._base(receipt, attempt), "pid": pid},
            )
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base(receipt, attempt),
                "pid": pid,
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
            "target": contract.target,
            "postcondition": "inspect_platform",
        }
        return AdapterResult(outcome=AppOutcome.SUCCESS, evidence=evidence)

    def _base(
        self, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> dict[str, str]:
        return {"receipt_id": receipt.id, "attempt_id": attempt.id}