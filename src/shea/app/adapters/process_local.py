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
from shea.app.exceptions import ContractValidationError
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
        # Context is expected on contract.metadata for Phase 2 wiring
        ctx: AdapterContext | None = contract.metadata.get("_adapter_context")
        argv = contract.arguments.get("argv")
        if not isinstance(argv, list) or not all(
            isinstance(item, str) for item in cast(list[object], argv)
        ):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="arguments.argv must be list[str]",
            )
        argv = cast(list[str], argv)
        if not argv:
            return AdapterResult(outcome=AppOutcome.FAILURE, error="argv is empty")

        scope: ExecutionScope | None = None
        if ctx is not None:
            scope = ctx.scope
            self._check_executable_allowed(argv[0], scope)

        if scope is not None and scope.process.allow_shell:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="shell execution is not implemented in process.local",
            )

        env: dict[str, str] = {}
        if ctx is not None:
            env = dict(ctx.environ_allowlist)
        elif scope is not None and not scope.process.inherit_environ:
            env = {}

        timeout_s: float | None = None
        if scope and scope.resources.wall_time_ms is not None:
            timeout_s = scope.resources.wall_time_ms / 1000.0

        output_limit = (
            scope.resources.output_bytes
            if scope and scope.resources.output_bytes is not None
            else 1_000_000
        )

        try:
            completed = subprocess.run(  # noqa: S603 — argv list, no shell
                argv,
                capture_output=True,
                timeout=timeout_s,
                env=env if env or (scope and not scope.process.inherit_environ) else None,
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
                "argv0": argv[0],
            },
            error=None if outcome is AppOutcome.SUCCESS else f"exit {completed.returncode}",
        )

    def _check_executable_allowed(self, argv0: str, scope: ExecutionScope) -> None:
        allowed = scope.process.allowed_executables
        if not allowed:
            return
        name = Path(argv0).name
        if argv0 not in allowed and name not in allowed:
            raise ContractValidationError(
                f"executable {argv0!r} not in process scope allowlist"
            )