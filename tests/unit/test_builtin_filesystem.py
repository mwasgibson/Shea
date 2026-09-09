from __future__ import annotations

from pathlib import Path

import pytest

from shea.contracts.enums import ExecutionOutcome
from shea.contracts.models import Task, ToolExecutionRecord, ToolRequest
from shea.security.filesystem_policy import FilesystemPolicy
from shea.tools.builtin.filesystem import (
    filesystem_write_verifier,
    register_filesystem_tools,
)
from shea.tools.builtin.register import register_builtin_tools
from shea.tools.executor import ToolExecutor
from shea.tools.registry import ToolRegistry
from shea.verification.verifier import VerifierRegistry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


@pytest.fixture
def policy(workspace: Path) -> FilesystemPolicy:
    return FilesystemPolicy(allowed_roots=frozenset({str(workspace)}))


@pytest.fixture
def registry(policy: FilesystemPolicy) -> ToolRegistry:
    reg = ToolRegistry()
    verifiers = VerifierRegistry()
    register_filesystem_tools(reg, policy, verifier_registry=verifiers)
    return reg


def test_register_builtin_tools_registers_read_and_write(policy: FilesystemPolicy) -> None:
    reg = ToolRegistry()
    register_builtin_tools(reg, filesystem_policy=policy)
    names = {d.name for d in reg.list_tools()}
    assert "filesystem.read" in names
    assert "filesystem.write" in names


def test_write_and_read_under_root(workspace: Path, registry: ToolRegistry) -> None:
    executor = ToolExecutor(registry, allow_unsafe_execution=True)
    path = str(workspace / "hello.txt")
    write_req = ToolRequest(
        request_id="r1",
        tool="filesystem.write",
        action="write",
        arguments={"path": path, "content": "hello shea"},
    )
    result = executor.execute(write_req, authorized_capabilities=frozenset({"filesystem.write"}))
    assert result.outcome is ExecutionOutcome.SUCCESS
    assert (workspace / "hello.txt").read_text(encoding="utf-8") == "hello shea"

    read_req = ToolRequest(
        request_id="r2",
        tool="filesystem.read",
        action="read",
        arguments={"path": path},
    )
    read_result = executor.execute(
        read_req, authorized_capabilities=frozenset({"filesystem.read"})
    )
    assert read_result.outcome is ExecutionOutcome.SUCCESS
    assert read_result.response is not None
    assert read_result.response.data["content"] == "hello shea"


def test_write_outside_root_fails(tmp_path: Path, registry: ToolRegistry) -> None:
    executor = ToolExecutor(registry, allow_unsafe_execution=True)
    outside = str(tmp_path / "outside.txt")
    req = ToolRequest(
        request_id="r3",
        tool="filesystem.write",
        action="write",
        arguments={"path": outside, "content": "nope"},
    )
    result = executor.execute(req, authorized_capabilities=frozenset({"filesystem.write"}))
    assert result.outcome is ExecutionOutcome.FAILURE
    assert not Path(outside).exists()


def test_write_verifier_confirms_content(workspace: Path) -> None:
    path = workspace / "verified.txt"
    path.write_text("payload", encoding="utf-8")
    record = ToolExecutionRecord(
        id="e1",
        task_id="t1",
        tool="filesystem.write",
        action="write",
        outcome=ExecutionOutcome.SUCCESS,
        success=True,
        data={"path": str(path), "content": "payload"},
    )
    task = Task(
        id="t1",
        session_id="s",
        request_id="r",
        state=__import__("shea.contracts.enums", fromlist=["TaskState"]).TaskState.VERIFYING,
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    outcome = filesystem_write_verifier(task, record)
    assert outcome.verified is True
    assert outcome.method == "filesystem.content_match"