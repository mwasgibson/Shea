from __future__ import annotations

from shea.app.contracts import ExecutionContract
from shea.app.exceptions import ContractValidationError
from shea.app.scopes import (
    EnforcementStatus,
    ExecutionScope,
    ScopeEnforcementReport,
)


def evaluate_scope(
    scope: ExecutionScope, contract: ExecutionContract | None = None
) -> ScopeEnforcementReport:
    """Report what V1 can enforce. Required controls that cannot be
    honored fail closed (EP technical design § isolation / ports).
    """
    limits: dict[str, EnforcementStatus] = {}
    isolation: dict[str, EnforcementStatus] = {}
    filesystem: dict[str, EnforcementStatus] = {}
    network: dict[str, EnforcementStatus] = {}
    application: dict[str, EnforcementStatus] = {}

    # --- resources ---
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

    # --- isolation ---
    if scope.isolation.require_cgroup:
        isolation["cgroup"] = EnforcementStatus.UNSUPPORTED
    else:
        isolation["cgroup"] = EnforcementStatus.NOT_REQUESTED

    if scope.isolation.require_new_session:
        isolation["new_session"] = EnforcementStatus.PARTIALLY_ENFORCED
    else:
        isolation["new_session"] = EnforcementStatus.NOT_REQUESTED

    # --- filesystem ---
    if scope.filesystem.allowed_roots:
        filesystem["allowed_roots"] = EnforcementStatus.ENFORCED
    else:
        filesystem["allowed_roots"] = EnforcementStatus.NOT_REQUESTED

    if scope.filesystem.read_only:
        filesystem["read_only"] = EnforcementStatus.ENFORCED
    else:
        filesystem["read_only"] = EnforcementStatus.NOT_REQUESTED

    if getattr(scope.filesystem, "write_only", False):
        filesystem["write_only"] = EnforcementStatus.ENFORCED
    else:
        filesystem["write_only"] = EnforcementStatus.NOT_REQUESTED

    # --- network ---
    if scope.network.allowed_hosts is not None:
        network["allowed_hosts"] = EnforcementStatus.ENFORCED
    else:
        network["allowed_hosts"] = EnforcementStatus.NOT_REQUESTED

    if scope.network.block_private:
        network["block_private"] = EnforcementStatus.ENFORCED
    else:
        network["block_private"] = EnforcementStatus.NOT_REQUESTED

    # --- application ---
    app = scope.application
    if app.allowed_executables:
        application["allowed_executables"] = EnforcementStatus.ENFORCED
    else:
        application["allowed_executables"] = EnforcementStatus.NOT_REQUESTED

    if app.allowed_desktop_ids:
        application["allowed_desktop_ids"] = EnforcementStatus.ENFORCED
    else:
        application["allowed_desktop_ids"] = EnforcementStatus.NOT_REQUESTED

    if app.allowed_bundle_ids or app.allowed_app_names:
        application["allowed_mac_ids"] = EnforcementStatus.ENFORCED
    else:
        application["allowed_mac_ids"] = EnforcementStatus.NOT_REQUESTED

    if app.allow_xdg_open:
        application["allow_xdg_open"] = EnforcementStatus.ENFORCED
    else:
        application["allow_xdg_open"] = EnforcementStatus.NOT_REQUESTED

    if app.allow_terminate:
        application["allow_terminate"] = EnforcementStatus.ENFORCED
    else:
        application["allow_terminate"] = EnforcementStatus.NOT_REQUESTED

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

    if contract is not None:
        op = contract.operation
        cap = contract.capability

        if (
            op.startswith("filesystem.")
            or cap in {"filesystem.read", "filesystem.write"}
        ) and not scope.filesystem.allowed_roots:
            required_unsupported.append("filesystem.allowed_roots")

        if op.startswith("network.") or op.startswith("browser.") or cap in {
            "network.connect",
            "network.request",
            "browser.navigate",
            "browser.read",
        }:
            # V1: private-block must be on for browser/network, or explicit allowlist
            if not scope.network.block_private and scope.network.allowed_hosts is None:
                required_unsupported.append("network.block_private_or_allowed_hosts")

        if op.startswith("application.") or cap.startswith("application."):
            launch_like = op in {
                "application.launch",
                "application.activate",
            } or cap in {"application.launch", "application.activate"}
            if launch_like:
                has_any = bool(
                    app.allowed_executables
                    or app.allowed_desktop_ids
                    or app.allowed_bundle_ids
                    or app.allowed_app_names
                    or app.allow_xdg_open
                )
                if not has_any:
                    required_unsupported.append("application.allowlist")

            if op == "application.terminate" or cap == "application.terminate":
                if not app.allow_terminate:
                    required_unsupported.append("application.allow_terminate")

    if required_unsupported:
        raise ContractValidationError(
            "scope cannot be enforced: unsupported or missing required controls: "
            f"{required_unsupported}"
        )

    return ScopeEnforcementReport(
        scope_id=scope.scope_id,
        limits=limits,
        isolation=isolation,
        filesystem=filesystem,
        # If ScopeEnforcementReport does not yet have these fields, add them:
        # network=network, application=application,
        acceptable=True,
        detail="ok",
    )