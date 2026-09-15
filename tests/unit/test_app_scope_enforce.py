from __future__ import annotations

import pytest

from shea.app.contracts import ExecutionContract
from shea.app.exceptions import ContractValidationError
from shea.app.scope_enforce import evaluate_scope
from shea.app.scopes import (
    ApplicationScope,
    EnforcementStatus,
    ExecutionScope,
    FilesystemScope,
    IsolationPolicy,
    NetworkScope,
    ResourceLimits,
)


def _contract(
    *,
    operation: str,
    capability: str | None = None,
    target: str = "demo",
) -> ExecutionContract:
    return ExecutionContract(
        contract_id="c-scope-1",
        authorization_id="auth-1",
        capability=capability or operation.rsplit(".", 1)[0] + ".op",
        operation=operation,
        target=target,
    )


def test_evaluate_scope_without_contract_is_acceptable() -> None:
    scope = ExecutionScope(scope_id="s1")
    report = evaluate_scope(scope)
    assert report.acceptable is True
    assert report.scope_id == "s1"
    assert report.limits["wall_time_ms"] is EnforcementStatus.ENFORCED
    assert report.network["block_private"] is EnforcementStatus.ENFORCED
    assert report.application["allowed_executables"] is EnforcementStatus.NOT_REQUESTED


def test_cgroup_required_fails_closed() -> None:
    scope = ExecutionScope(
        scope_id="s-cgroup",
        isolation=IsolationPolicy(require_cgroup=True),
    )
    with pytest.raises(ContractValidationError, match="cgroup"):
        evaluate_scope(scope)


def test_memory_limit_required_fails_closed() -> None:
    scope = ExecutionScope(
        scope_id="s-mem",
        resources=ResourceLimits(memory_bytes=64 * 1024 * 1024),
    )
    with pytest.raises(ContractValidationError, match="memory_bytes"):
        evaluate_scope(scope)


def test_filesystem_operation_requires_allowed_roots() -> None:
    scope = ExecutionScope(
        scope_id="s-fs",
        filesystem=FilesystemScope(allowed_roots=frozenset()),
    )
    with pytest.raises(ContractValidationError, match="filesystem.allowed_roots"):
        evaluate_scope(scope, _contract(operation="filesystem.read", capability="filesystem.read"))


def test_filesystem_operation_with_roots_ok() -> None:
    scope = ExecutionScope(
        scope_id="s-fs-ok",
        filesystem=FilesystemScope(allowed_roots=frozenset({"/tmp/ws"})),
    )
    report = evaluate_scope(
        scope,
        _contract(operation="filesystem.write", capability="filesystem.write"),
    )
    assert report.filesystem["allowed_roots"] is EnforcementStatus.ENFORCED
    assert report.acceptable is True


def test_application_launch_requires_allowlist() -> None:
    scope = ExecutionScope(
        scope_id="s-app",
        application=ApplicationScope(),
    )
    with pytest.raises(ContractValidationError, match="application.allowlist"):
        evaluate_scope(
            scope,
            _contract(operation="application.launch", capability="application.launch"),
        )


def test_application_launch_with_app_name_allowlist_ok() -> None:
    scope = ExecutionScope(
        scope_id="s-app-ok",
        application=ApplicationScope(allowed_app_names=frozenset({"TextEdit"})),
    )
    report = evaluate_scope(
        scope,
        _contract(operation="application.launch", capability="application.launch"),
    )
    assert report.application["allowed_mac_ids"] is EnforcementStatus.ENFORCED
    assert report.acceptable is True


def test_application_terminate_requires_flag() -> None:
    scope = ExecutionScope(
        scope_id="s-term",
        application=ApplicationScope(
            allowed_executables=frozenset({"true"}),
            allow_terminate=False,
        ),
    )
    with pytest.raises(ContractValidationError, match="application.allow_terminate"):
        evaluate_scope(
            scope,
            _contract(
                operation="application.terminate",
                capability="application.terminate",
            ),
        )


def test_application_terminate_allowed_when_flag_set() -> None:
    scope = ExecutionScope(
        scope_id="s-term-ok",
        application=ApplicationScope(allow_terminate=True),
    )
    report = evaluate_scope(
        scope,
        _contract(
            operation="application.terminate",
            capability="application.terminate",
        ),
    )
    assert report.application["allow_terminate"] is EnforcementStatus.ENFORCED


def test_network_without_private_block_or_allowlist_fails() -> None:
    scope = ExecutionScope(
        scope_id="s-net-bad",
        network=NetworkScope(allowed_hosts=None, block_private=False),
    )
    with pytest.raises(
        ContractValidationError, match="network.block_private_or_allowed_hosts"
    ):
        evaluate_scope(
            scope,
            _contract(operation="network.request", capability="network.request"),
        )


def test_network_with_block_private_ok() -> None:
    scope = ExecutionScope(
        scope_id="s-net-ok",
        network=NetworkScope(allowed_hosts=None, block_private=True),
    )
    report = evaluate_scope(
        scope,
        _contract(operation="network.request", capability="network.request"),
    )
    assert report.network["block_private"] is EnforcementStatus.ENFORCED


def test_browser_operation_uses_network_scope_rules() -> None:
    scope = ExecutionScope(
        scope_id="s-br-bad",
        network=NetworkScope(allowed_hosts=None, block_private=False),
    )
    with pytest.raises(ContractValidationError, match="network.block_private"):
        evaluate_scope(
            scope,
            _contract(operation="browser.navigate", capability="browser.navigate"),
        )


def test_browser_with_host_allowlist_ok() -> None:
    scope = ExecutionScope(
        scope_id="s-br-ok",
        network=NetworkScope(
            allowed_hosts=frozenset({"example.com"}),
            block_private=False,
        ),
    )
    report = evaluate_scope(
        scope,
        _contract(operation="browser.read", capability="browser.read"),
    )
    assert report.network["allowed_hosts"] is EnforcementStatus.ENFORCED
    assert report.acceptable is True