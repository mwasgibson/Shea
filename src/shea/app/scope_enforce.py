from __future__ import annotations

from shea.app.contracts import ExecutionContract
from shea.app.exceptions import ContractValidationError
from shea.app.scopes import (
    EnforcementStatus,
    ExecutionScope,
    ScopeEnforcementReport,
)


def evaluate_scope(scope: ExecutionScope, contract: ExecutionContract | None = None) -> ScopeEnforcementReport:
    """Report what V1 can enforce. Required isolation/limits that are
    UNSUPPORTED fail closed (EP §5.4).
    
    Filesystem validation: empty allowed_roots with filesystem operations
    fails closed.
    """
    limits: dict[str, EnforcementStatus] = {}
    isolation: dict[str, EnforcementStatus] = {}
    filesystem: dict[str, EnforcementStatus] = {}

    if scope.resources.wall_time_ms is not None:
        limits["wall_time_ms"] = EnforcementStatus.ENFORCED
    else:
        limits["wall_time_ms"] = EnforcementStatus.NOT_REQUESTED

    if scope.resources.output_bytes is not None:
        limits["output_bytes"] = EnforcementStatus.ENFORCED
    else:
        limits["output_bytes"] = EnforcementStatus.NOT_REQUESTED

    if scope.resources.memory_bytes is not None:
        limits["memory_bytes"] = EnforcementStatus.UNSUPPORTED
    else:
        limits["memory_bytes"] = EnforcementStatus.NOT_REQUESTED

    if scope.isolation.require_cgroup:
        isolation["cgroup"] = EnforcementStatus.UNSUPPORTED
    else:
        isolation["cgroup"] = EnforcementStatus.NOT_REQUESTED

    if scope.isolation.require_new_session:
        isolation["new_session"] = EnforcementStatus.PARTIALLY_ENFORCED
    else:
        isolation["new_session"] = EnforcementStatus.NOT_REQUESTED

    if scope.filesystem.allowed_roots:
        filesystem["allowed_roots"] = EnforcementStatus.ENFORCED
    else:
        filesystem["allowed_roots"] = EnforcementStatus.NOT_REQUESTED

    if scope.filesystem.read_only:
        filesystem["read_only"] = EnforcementStatus.ENFORCED
    else:
        filesystem["read_only"] = EnforcementStatus.NOT_REQUESTED
        
    if scope.filesystem.write_only:
        filesystem["write_only"] = EnforcementStatus.ENFORCED
    else:
        filesystem["write_only"] = EnforcementStatus.NOT_REQUESTED

    required_unsupported: list[str] = []
    if (
        scope.resources.memory_bytes is not None
        and limits["memory_bytes"] is EnforcementStatus.UNSUPPORTED
    ):
        required_unsupported.append("memory_bytes")
    if (
        scope.isolation.require_cgroup
        and isolation["cgroup"] is EnforcementStatus.UNSUPPORTED
    ):
        required_unsupported.append("cgroup")

    if (
        contract is not None
        and (contract.operation.startswith("filesystem.") 
             or contract.capability in {"filesystem.read", "filesystem.write"})
        and not scope.filesystem.allowed_roots
    ):
        required_unsupported.append("filesystem.allowed_roots")

    if required_unsupported:
        raise ContractValidationError(
            f"scope cannot be enforced: unsupported required controls: "
            f"{required_unsupported}"
        )

    return ScopeEnforcementReport(
        scope_id=scope.scope_id,
        limits=limits,
        isolation=isolation,
        filesystem=filesystem,
        acceptable=True,
        detail="ok",
    )
