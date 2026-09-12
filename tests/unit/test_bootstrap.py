from __future__ import annotations

from pathlib import Path

from shea.bootstrap import build_runtime


def test_build_runtime_starts(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path / "shea.db")

    assert runtime.reconcile_app_plane() == []
    registered_tools = {tool.name for tool in runtime.tool_registry.list_tools()}
    assert {"filesystem.read", "filesystem.write"} <= registered_tools
    runtime.conn.close()
