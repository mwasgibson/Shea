from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.app.ports.process import AdapterContext
from shea.app.scopes import ExecutionScope


class LocalProcessAdapter:
    """V1 process adapter: no shell, controlled env, wall-time + output bounds."""

    name = "process.local"

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.operation in {
            "process.spawn",
            "process.run",
        } or contract.capability in {"process.execute", "process.spawn"}

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
                error="process.local requires AdapterContext with scope",
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )

        argv = contract.arguments.get("argv")
        if not isinstance(argv, list) or not all(
            isinstance(item, str) for item in cast(list[object], argv)
        ):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="arguments.argv must be list[str]",
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )
        argv_list = cast(list[str], argv)
        if not argv_list:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="argv is empty",
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )

        scope: ExecutionScope = ctx.scope
        allow_err = self._executable_allow_error(argv_list[0], scope)
        if allow_err is not None:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=allow_err,
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )

        if scope.process.allow_shell:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="shell execution is not implemented in process.local",
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )

        if scope.process.inherit_environ:
            env: dict[str, str] | None = None
            if ctx.environ_allowlist:
                # Explicit allowlist replaces full inherit when provided
                env = dict(ctx.environ_allowlist)
        else:
            env = dict(ctx.environ_allowlist)
            if not ctx.environ_allowlist:
                env = {}

        timeout_s: float | None = None
        if scope.resources.wall_time_ms is not None:
            timeout_s = scope.resources.wall_time_ms / 1000.0

        output_limit = (
            scope.resources.output_bytes
            if scope.resources.output_bytes is not None
            else 1_000_000
        )

        try:
            completed = subprocess.run(  # noqa: S603 — argv list, no shell
                argv_list,
                capture_output=True,
                timeout=timeout_s,
                env=env,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return AdapterResult(
                outcome=AppOutcome.UNKNOWN,
                error=f"wall_time exceeded: {exc}",
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )
        except OSError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )

        stdout = completed.stdout[:output_limit]
        stderr = completed.stderr[:output_limit]
        outcome = (
            AppOutcome.SUCCESS if completed.returncode == 0 else AppOutcome.FAILURE
        )
        return AdapterResult(
            outcome=outcome,
            evidence={
                "receipt_id": receipt.id,
                "attempt_id": attempt.id,
                "returncode": completed.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "argv0": argv_list[0],
            },
            error=None if outcome is AppOutcome.SUCCESS else f"exit {completed.returncode}",
        )

    def _executable_allow_error(
        self, argv0: str, scope: ExecutionScope
    ) -> str | None:
        allowed = scope.process.allowed_executables
        if not allowed:
            # Empty allowlist = deny all (fail closed)
            return "process scope allowed_executables is empty; refusing spawn"
        name = Path(argv0).name
        if argv0 not in allowed and name not in allowed:
            return f"executable {argv0!r} not in process scope allowlist"
        return None