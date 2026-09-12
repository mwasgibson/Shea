from __future__ import annotations

from pathlib import Path

from shea.bootstrap import build_runtime
from shea.contracts.enums import TaskState


def test_build_runtime_starts(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    runtime = build_runtime(tmp_path / "shea.db", workspace=workspace)

    assert runtime.reconcile_app_plane() == []
    names = {tool.name for tool in runtime.tool_registry.list_tools()}
    assert {"filesystem.read", "filesystem.write"} <= names
    runtime.conn.close()


def test_handle_text_write_note_plan_only(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    runtime = build_runtime(tmp_path / "shea.db", workspace=workspace)

    result = runtime.interaction_service.handle_text(
        "write a note",
        run=False,
    )
    assert result.error is None
    assert result.task.state is TaskState.READY
    assert result.planning.plan is not None
    assert len(result.planning.plan.steps) == 1
    assert result.planning.plan.steps[0].tool == "filesystem.write"
    runtime.conn.close()


def test_handle_text_write_note_executes(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    runtime = build_runtime(
        tmp_path / "shea.db",
        workspace=workspace,
        allow_unsafe_execution=True,
    )

    result = runtime.interaction_service.handle_text(
        "write a note",
        explicit_user_ack=True,
        run=True,
    )
    assert result.error is None
    assert result.run is not None
    assert result.task.state is TaskState.COMPLETED
    assert result.run.stopped_early is False
    note = workspace / "note.txt"
    assert note.is_file()
    assert note.read_text(encoding="utf-8") == "hello from shea"
    runtime.conn.close()