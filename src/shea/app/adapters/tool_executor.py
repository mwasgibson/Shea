from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.contracts.models import ToolRequest
from shea.credentials.injection import resolve_argument_credentials
from shea.credentials.ports import CredentialBroker
from shea.execution.permit import ExecutionPermit, ExecutionPermitAuthority

if TYPE_CHECKING:
    from shea.tools.executor import ToolExecutor


class ToolExecutorAdapter:
    """Bridge ToolExecutor into the app execution plane.

    Credential refs stay on the contract. Secrets are injected here only,
    after permit verification, immediately before the handler runs.
    """

    name = "tool_executor"

    def __init__(
        self,
        tool_executor: ToolExecutor,
        *,
        permit_authority: ExecutionPermitAuthority | None = None,
        credential_broker: CredentialBroker | None = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._permits = permit_authority or ExecutionPermitAuthority()
        self._credential_broker = credential_broker

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
            for value in contract.metadata.get("_authorized_capabilities", ())
        )

        tool_context = cast(
            dict[str, Any],
            contract.metadata.get("tool_context", {}),
        )
        # Permit is verified against *reference-shaped* arguments only.
        contract_arguments = dict(contract.arguments)
        if not self._permits.verify(
            permit,
            tool=str(contract.metadata["tool"]),
            action=str(contract.metadata["action"]),
            arguments=contract_arguments,
            capabilities=capabilities,
        ):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="execution permit invalid or capability/args mismatch",
                evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
            )

        tool_name = str(contract.metadata["tool"])
        profile_id = str(contract.metadata.get("_profile_id", "system"))
        handler_arguments = contract_arguments
        if self._credential_broker is not None:
            try:
                handler_arguments = resolve_argument_credentials(
                    contract_arguments,
                    broker=self._credential_broker,
                    tool=tool_name,
                    profile_id=profile_id,
                )
            except Exception as exc:
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error=f"credential injection failed: {exc}",
                    evidence={"receipt_id": receipt.id, "attempt_id": attempt.id},
                )

        request = ToolRequest(
            request_id=str(
                contract.metadata.get("request_id", contract.contract_id)
            ),
            tool=tool_name,
            action=str(contract.metadata["action"]),
            arguments=handler_arguments,
            context={**tool_context, "_execution_permit": permit_data},
        )

        result = self._tool_executor.execute(request, capabilities)
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