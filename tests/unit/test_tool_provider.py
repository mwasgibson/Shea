from __future__ import annotations

from pathlib import Path

from shea.security.filesystem_policy import FilesystemPolicy
from shea.tools.builtin.providers import BuiltinFilesystemProvider
from shea.tools.provider import load_tools
from shea.tools.registry import ToolRegistry
from shea.verification.verifier import VerifierRegistry


def test_load_tools_registers_filesystem(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    registry = ToolRegistry()
    verifiers = VerifierRegistry()
    policy = FilesystemPolicy(allowed_roots=frozenset({str(root)}))

    loaded = load_tools(
        registry,
        [BuiltinFilesystemProvider(policy)],
        verifier_registry=verifiers,
    )

    assert loaded == ["shea.builtin.filesystem"]
    names = {d.name for d in registry.list_tools()}
    assert "filesystem.read" in names
    assert "filesystem.write" in names
    assert verifiers.get("filesystem.write") is not verifiers.get("missing.tool")