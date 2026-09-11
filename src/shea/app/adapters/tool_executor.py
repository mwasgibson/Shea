from __future__ import annotations

from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.contracts.models import ToolRequest
from shea.tools.executor import ToolExecutor


class ToolExecutorAdapter:
    """Bridge ToolExecutor into the app execution plane."""

    name = "tool_executor"

    def __init__(self, tool_executor: ToolExecutor) -> None:
        self._tool_executor = tool_executor

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.metadata.get("execution_backend") == self.name

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        capabilities = frozenset(
            str(value)
            for value in contract.metadata.get(
                "_authorized_capabilities",
                (),
            )
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
            context=dict(
                contract.metadata.get(
                    "tool_context",
                    {},
                )
            ),
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