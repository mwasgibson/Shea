from __future__ import annotations

import platform

from shea.app.adapters.application_policy import (
    app_name_allowed,
    bundle_id_allowed,
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


class ApplicationStubAdapter:
    """Phase 3 placeholder — real app control is Phase 6 platform work."""

    name = "application.stub"

    def supports(self, contract: ExecutionContract) -> bool:
        if platform.system() in {"Darwin", "Windows", "Linux"}:
            pass
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
                error="application.stub requires scope + AdapterContext",
                evidence=self._base(receipt, attempt),
            )
        app_scope = ctx.scope.application

        if contract.operation in {"application.launch", "application.activate"}:
            return self._launch(contract, receipt, attempt, app_scope)
        if contract.operation == "application.terminate":
            return self._terminate(contract, receipt, attempt, app_scope)
        if contract.operation == "application.inspect":
            return self._inspect(contract, receipt, attempt)
        return AdapterResult(
            outcome=AppOutcome.FAILURE,
            error=f"unsupported operation: {contract.operation!r}",
            evidence=self._base(receipt, attempt),
        )

    def _launch(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
        app_scope: ApplicationScope,
    ) -> AdapterResult:
        path = contract.arguments.get("path")
        desktop_id = contract.arguments.get("desktop_id")
        bundle_id = contract.arguments.get("bundle_id")
        app_name = contract.arguments.get("name") or contract.target

        allowed = (
            isinstance(path, str) and executable_allowed(path, app_scope)
        ) or (
            isinstance(desktop_id, str) and desktop_id_allowed(desktop_id, app_scope)
        ) or (
            isinstance(bundle_id, str) and bundle_id_allowed(bundle_id, app_scope)
        ) or (
            isinstance(app_name, str) and app_name_allowed(app_name, app_scope)
        )
        if not allowed:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="application target is not allowed by application scope",
                evidence=self._base(receipt, attempt),
            )
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base(receipt, attempt),
                "operation": contract.operation,
                "target": contract.target,
                "simulated": True,
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
        pid = contract.arguments.get("pid")
        if not isinstance(pid, int) and not (isinstance(pid, str) and pid.isdigit()):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="application.terminate requires arguments.pid (int)",
                evidence=self._base(receipt, attempt),
            )
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base(receipt, attempt),
                "pid": int(pid),
                "simulated": True,
                "postcondition": "terminate_requested",
            },
        )

    def _inspect(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base(receipt, attempt),
                "platform": platform.platform(),
                "system": platform.system(),
                "target": contract.target,
                "simulated": True,
                "postcondition": "inspect_platform",
            },
        )

    def _base(
        self, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> dict[str, str]:
        return {"receipt_id": receipt.id, "attempt_id": attempt.id}