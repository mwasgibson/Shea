from __future__ import annotations

import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shea.app.adapters.application_linux import LinuxApplicationAdapter
from shea.app.adapters.application_macos import MacOSApplicationAdapter
from shea.app.adapters.application_policy import (
    app_name_allowed,
    bundle_id_allowed,
    desktop_id_allowed,
    executable_allowed,
)
from shea.app.adapters.application_windows import WindowsApplicationAdapter
from shea.app.adapters.base import Adapter
from shea.app.contracts import (
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome, AttemptState, ReceiptState
from shea.app.identities import (
    IdentityAssurance,
    IdentityKind,
    ResolvedIdentity,
    VerifiedIdentity,
)
from shea.app.ports.process import AdapterContext
from shea.app.scopes import ApplicationScope, ExecutionScope, ScopeEnforcementReport


def _now() -> datetime:
    return datetime.now(UTC)


def _receipt_attempt(
    *,
    operation: str = "application.launch",
    target: str = "demo",
) -> tuple[ExecutionReceipt, ExecutionAttempt]:
    now = _now()
    receipt = ExecutionReceipt(
        id="r-app-1",
        contract_id="c-app-1",
        authorization_id="auth-1",
        capability="application.launch",
        operation=operation,
        target=target,
        state=ReceiptState.ATTEMPTING,
        created_at=now,
        adapter_name="test",
    )
    attempt = ExecutionAttempt(
        id="a-app-1",
        receipt_id=receipt.id,
        attempt_number=1,
        state=AttemptState.INVOKED,
        created_at=now,
        invoked_at=now,
        adapter_name="test",
    )
    return receipt, attempt


def _verified() -> VerifiedIdentity:
    # Adjust fields if your VerifiedIdentity shape differs
    return VerifiedIdentity(
        identity=ResolvedIdentity(
            kind=IdentityKind.OPAQUE,
            canonical_value="demo",
            requested_value="demo",
        ),
        method="demo",
        assurance=IdentityAssurance.BASIC,
        detail="demo",
        verified=True,
    )


def _enforcement(scope_id: str = "app") -> ScopeEnforcementReport:
    return ScopeEnforcementReport(
        scope_id=scope_id,
        limits={},
        isolation={},
        acceptable=True,
        detail="ok",
        filesystem={},
    )


def _ctx(scope: ExecutionScope) -> AdapterContext:
    return AdapterContext(
        verified_identity=_verified(),
        scope=scope,
        enforcement=_enforcement(scope.scope_id),
    )


def _contract(
    *,
    operation: str = "application.launch",
    target: str = "demo",
    arguments: dict[str, Any] | None = None,
    scope: ExecutionScope | None = None,
    with_context: bool = True,
) -> ExecutionContract:
    scope = scope or ExecutionScope(scope_id="app")
    metadata: dict[str, Any] = {}
    if with_context:
        metadata["_adapter_context"] = _ctx(scope)
    return ExecutionContract(
        contract_id="c-app-1",
        authorization_id="auth-1",
        capability="application.launch",
        operation=operation,
        target=target,
        arguments=dict(arguments or {}),
        metadata=metadata,
        scope=scope,
    )


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------


def test_empty_allowlist_denies_executable() -> None:
    assert executable_allowed("/usr/bin/firefox", ApplicationScope()) is False


def test_executable_allowed_by_basename_and_path() -> None:
    scope = ApplicationScope(
        allowed_executables=frozenset({"firefox", "/usr/bin/firefox"})
    )
    assert executable_allowed("/usr/bin/firefox", scope) is True
    assert executable_allowed("firefox", scope) is True
    assert executable_allowed("/usr/bin/chrome", scope) is False


def test_desktop_id_allowed_variants() -> None:
    scope = ApplicationScope(allowed_desktop_ids=frozenset({"firefox"}))
    assert desktop_id_allowed("firefox", scope) is True
    assert desktop_id_allowed("firefox.desktop", scope) is True
    assert desktop_id_allowed("chrome.desktop", scope) is False


def test_bundle_and_app_name_allowlists() -> None:
    scope = ApplicationScope(
        allowed_bundle_ids=frozenset({"com.apple.TextEdit"}),
        allowed_app_names=frozenset({"TextEdit"}),
    )
    assert bundle_id_allowed("com.apple.TextEdit", scope) is True
    assert bundle_id_allowed("com.apple.Safari", scope) is False
    assert app_name_allowed("TextEdit", scope) is True
    assert app_name_allowed("Safari", scope) is False


# ---------------------------------------------------------------------------
# supports() is platform-gated
# ---------------------------------------------------------------------------


def test_macos_supports_only_on_darwin() -> None:
    adapter = MacOSApplicationAdapter()
    contract = _contract(operation="application.launch")
    if platform.system() == "Darwin":
        assert adapter.supports(contract) is True
    else:
        assert adapter.supports(contract) is False


def test_windows_supports_only_on_windows() -> None:
    adapter = WindowsApplicationAdapter()
    contract = _contract(operation="application.launch")
    if platform.system() == "Windows":
        assert adapter.supports(contract) is True
    else:
        assert adapter.supports(contract) is False


def test_linux_supports_only_on_linux() -> None:
    adapter = LinuxApplicationAdapter()
    contract = _contract(operation="application.launch")
    if platform.system() == "Linux":
        assert adapter.supports(contract) is True
    else:
        assert adapter.supports(contract) is False


# ---------------------------------------------------------------------------
# All adapters: no context → fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter",
    [
        MacOSApplicationAdapter(),
        WindowsApplicationAdapter(),
        LinuxApplicationAdapter(),
    ],
)
def test_requires_adapter_context(adapter: Adapter) -> None:
    contract = _contract(with_context=False, arguments={"name": "TextEdit"})
    receipt, attempt = _receipt_attempt()
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE
    assert "scope" in (result.error or "").lower() or "context" in (
        result.error or ""
    ).lower()


# ---------------------------------------------------------------------------
# macOS allowlist
# ---------------------------------------------------------------------------


def test_macos_launch_denied_empty_app_name_allowlist() -> None:
    adapter = MacOSApplicationAdapter()
    scope = ExecutionScope(
        scope_id="app",
        application=ApplicationScope(allowed_app_names=frozenset()),
    )
    contract = _contract(
        arguments={"name": "TextEdit"},
        target="TextEdit",
        scope=scope,
    )
    receipt, attempt = _receipt_attempt(target="TextEdit")
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE
    assert "allowlist" in (result.error or "").lower()


def test_macos_launch_denied_wrong_bundle_id() -> None:
    adapter = MacOSApplicationAdapter()
    scope = ExecutionScope(
        scope_id="app",
        application=ApplicationScope(
            allowed_bundle_ids=frozenset({"com.apple.TextEdit"}),
        ),
    )
    contract = _contract(
        arguments={"bundle_id": "com.apple.Safari"},
        target="Safari",
        scope=scope,
    )
    receipt, attempt = _receipt_attempt()
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE
    assert "allowlist" in (result.error or "").lower()


@patch("shea.app.adapters.application_macos.shutil.which", return_value="/usr/bin/open")
@patch("shea.app.adapters.application_macos.subprocess.run")
def test_macos_launch_allowed_name_invokes_open(
    mock_run: MagicMock, _which: MagicMock
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr=b"", stdout=b"")
    adapter = MacOSApplicationAdapter()
    scope = ExecutionScope(
        scope_id="app",
        application=ApplicationScope(allowed_app_names=frozenset({"TextEdit"})),
    )
    contract = _contract(
        arguments={"name": "TextEdit"},
        target="TextEdit",
        scope=scope,
    )
    receipt, attempt = _receipt_attempt(target="TextEdit")
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.SUCCESS
    assert result.evidence.get("postcondition") == "open_accepted"
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "open"
    assert "TextEdit" in cmd


# ---------------------------------------------------------------------------
# Windows allowlist
# ---------------------------------------------------------------------------


def test_windows_launch_denied_empty_executable_allowlist() -> None:
    adapter = WindowsApplicationAdapter()
    scope = ExecutionScope(
        scope_id="app",
        application=ApplicationScope(allowed_executables=frozenset()),
    )
    contract = _contract(
        arguments={"path": "C:\\Windows\\System32\\notepad.exe"},
        scope=scope,
    )
    receipt, attempt = _receipt_attempt()
    with patch(
        "shea.app.adapters.application_windows.Path.is_file", return_value=True
    ):
        result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE
    assert "allowlist" in (result.error or "").lower()


@patch("shea.app.adapters.application_windows.subprocess.Popen")
def test_windows_launch_allowed_path(mock_popen: MagicMock, tmp_path: Path) -> None:
    exe = tmp_path / "notepad.exe"
    exe.write_bytes(b"MZ")
    mock_popen.return_value = MagicMock(pid=4242)

    adapter = WindowsApplicationAdapter()
    scope = ExecutionScope(
        scope_id="app",
        application=ApplicationScope(
            allowed_executables=frozenset({"notepad.exe", str(exe.resolve())}),
        ),
    )
    contract = _contract(arguments={"path": str(exe)}, scope=scope)
    receipt, attempt = _receipt_attempt()
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.SUCCESS
    assert result.evidence.get("postcondition") == "open_accepted"
    assert result.evidence.get("pid") == 4242
    mock_popen.assert_called_once()
    assert mock_popen.call_args[1].get("shell") is False


def test_windows_terminate_disabled_by_scope() -> None:
    adapter = WindowsApplicationAdapter()
    scope = ExecutionScope(
        scope_id="app",
        application=ApplicationScope(allow_terminate=False),
    )
    contract = _contract(
        operation="application.terminate",
        arguments={"pid": 1234},
        scope=scope,
    )
    receipt, attempt = _receipt_attempt(operation="application.terminate")
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE
    assert "terminate" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Linux allowlist
# ---------------------------------------------------------------------------


def test_linux_desktop_id_denied() -> None:
    adapter = LinuxApplicationAdapter()
    scope = ExecutionScope(
        scope_id="app",
        application=ApplicationScope(allowed_desktop_ids=frozenset({"firefox"})),
    )
    contract = _contract(
        arguments={"desktop_id": "chrome.desktop"},
        scope=scope,
    )
    receipt, attempt = _receipt_attempt()
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE
    assert "allowlist" in (result.error or "").lower()


@patch("shea.app.adapters.application_linux.shutil.which", return_value="/usr/bin/gtk-launch")
@patch("shea.app.adapters.application_linux.subprocess.Popen")
def test_linux_desktop_id_allowed(
    mock_popen: MagicMock, _which: MagicMock
) -> None:
    mock_popen.return_value = MagicMock(pid=99)
    adapter = LinuxApplicationAdapter()
    scope = ExecutionScope(
        scope_id="app",
        application=ApplicationScope(allowed_desktop_ids=frozenset({"firefox"})),
    )
    contract = _contract(
        arguments={"desktop_id": "firefox.desktop"},
        scope=scope,
    )
    receipt, attempt = _receipt_attempt()
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.SUCCESS
    assert result.evidence.get("mode") == "gtk-launch"
    cmd = mock_popen.call_args[0][0]
    assert cmd == ["gtk-launch", "firefox.desktop"]


def test_linux_xdg_open_disabled_by_default() -> None:
    adapter = LinuxApplicationAdapter()
    scope = ExecutionScope(
        scope_id="app",
        application=ApplicationScope(allow_xdg_open=False),
    )
    contract = _contract(
        arguments={"xdg_uri": "https://example.com"},
        scope=scope,
    )
    receipt, attempt = _receipt_attempt()
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE
    assert "xdg-open" in (result.error or "").lower()


def test_linux_terminate_disabled_by_scope() -> None:
    adapter = LinuxApplicationAdapter()
    scope = ExecutionScope(
        scope_id="app",
        application=ApplicationScope(allow_terminate=False),
    )
    contract = _contract(
        operation="application.terminate",
        arguments={"pid": 99999},
        scope=scope,
    )
    receipt, attempt = _receipt_attempt(operation="application.terminate")
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.FAILURE


def test_linux_inspect_succeeds_with_context() -> None:
    adapter = LinuxApplicationAdapter()
    scope = ExecutionScope(scope_id="app")
    contract = _contract(
        operation="application.inspect",
        target="noop",
        scope=scope,
    )
    receipt, attempt = _receipt_attempt(operation="application.inspect")
    result = adapter.invoke(contract, receipt, attempt)
    assert result.outcome is AppOutcome.SUCCESS
    assert result.evidence.get("postcondition") == "inspect_platform"
    assert result.evidence.get("system") == platform.system()