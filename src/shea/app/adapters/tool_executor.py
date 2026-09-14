from __future__ import annotations

from typing import Any, cast

from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.contracts.models import ToolRequest
from shea.execution.permit import ExecutionPermit, ExecutionPermitAuthority
from shea.tools.executor import ToolExecutor


class ToolExecutorAdapter:
    """Bridge ToolExecutor into the app execution plane."""

    name = "tool_executor"

    def __init__(
        self,
        tool_executor: ToolExecutor,
        *,
        permit_authority: ExecutionPermitAuthority | None = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._permits = permit_authority or ExecutionPermitAuthority()

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.metadata.get("execution_backend") == self.name

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        raw = contract.metadata.get("_execution_permit")
        if not isinstance(raw, dict):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="tool_executor contract missing _execution_permit",
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )
        permit_data = cast(dict[str, Any], raw)
        permit = ExecutionPermit(
            token=str(permit_data["token"]),
            tool=str(permit_data["tool"]),
            action=str(permit_data["action"]),
            arguments_digest=str(permit_data["arguments_digest"]),
            capabilities_digest=str(permit_data["capabilities_digest"]),
        )
        capabilities = frozenset(
            str(value)
            for value in contract.metadata.get(
                "_authorized_capabilities",
                (),
            )
        )

        tool_context = cast(
            dict[str, Any],
            contract.metadata.get("tool_context", {}),
        )
        request = ToolRequest(
            request_id=str(
                contract.metadata.get(
                    "request_id",
                    contract.contract_id,
                )
            ),
            tool=str(contract.metadata["tool"]),
            action=str(contract.metadata["action"]),
            arguments=dict(contract.arguments),
            context={**tool_context, "_execution_permit": permit_data},
        )

        if not self._permits.verify(
            permit,
            tool=request.tool,
            action=request.action,
            arguments=request.arguments,
            capabilities=capabilities,
        ):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="execution permit invalid or capability/args mismatch",
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )

        result = self._tool_executor.execute(
            request,
            capabilities,
        )

        response = result.response

        outcome = {
            "SUCCESS": AppOutcome.SUCCESS,
            "FAILURE": AppOutcome.FAILURE,
            "UNKNOWN": AppOutcome.UNKNOWN,
        }[result.outcome.value]

        return AdapterResult(
            outcome=outcome,
            error=response.error,
            evidence={
                "receipt_id": receipt.id,
                "attempt_id": attempt.id,
                "tool": request.tool,
                "action": request.action,
                "data": response.data,
                "success": response.success,
            },
        )