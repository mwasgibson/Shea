from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from shea.contracts.enums import ExecutionOutcome, RiskLevel
from shea.contracts.models import Task, ToolExecutionRecord, ToolRequest, ToolResponse
from shea.security.exceptions import SecurityViolationError
from shea.security.filesystem_policy import FilesystemPolicy
from shea.security.runtime_checks import realpath_under_roots
from shea.tools.registry import ToolDeclaration, ToolRegistry
from shea.verification.verifier import VerificationOutcome, VerifierRegistry


def _read_handler(policy: FilesystemPolicy) -> Callable[[ToolRequest], ToolResponse]:
    def handler(request: ToolRequest) -> ToolResponse:
        raw_path = request.arguments.get("path")
        if not isinstance(raw_path, str):
            return ToolResponse(success=False, error="path must be a string")
        try:
            real = realpath_under_roots(raw_path, policy, tool="filesystem.read")
        except SecurityViolationError as exc:
            return ToolResponse(success=False, error=str(exc))

        if not real.is_file():
            return ToolResponse(
                success=False,
                error=f"Not a file or does not exist: {str(real)!r}",
            )
        try:
            content = real.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResponse(success=False, error=f"Read failed: {exc}")

        return ToolResponse(
            success=True,
            data={"path": str(real), "content": content},
        )

    return handler


def _write_handler(policy: FilesystemPolicy) -> Callable[[ToolRequest], ToolResponse]:
    def handler(request: ToolRequest) -> ToolResponse:
        raw_path = request.arguments.get("path")
        content = request.arguments.get("content")
        if not isinstance(raw_path, str):
            return ToolResponse(success=False, error="path must be a string")
        if not isinstance(content, str):
            return ToolResponse(success=False, error="content must be a string")

        try:
            real = realpath_under_roots(raw_path, policy, tool="filesystem.write")
        except SecurityViolationError as exc:
            return ToolResponse(success=False, error=str(exc))

        try:
            parent = real.parent
            realpath_under_roots(str(parent), policy, tool="filesystem.write")
            parent.mkdir(parents=True, exist_ok=True)
            real.write_text(content, encoding="utf-8")
        except SecurityViolationError as exc:
            return ToolResponse(success=False, error=str(exc))
        except OSError as exc:
            return ToolResponse(success=False, error=f"Write failed: {exc}")

        encoded = content.encode("utf-8")
        return ToolResponse(
            success=True,
            data={
                "path": str(real),
                "bytes_written": len(encoded),
                "content": content,
            },
        )

    return handler


def filesystem_write_verifier(
    task: Task, record: ToolExecutionRecord
) -> VerificationOutcome:
    """Independent check: file exists and content matches the write report."""
    if record.outcome is not ExecutionOutcome.SUCCESS or not record.success:
        return VerificationOutcome(
            verified=False,
            method="filesystem.content_match",
            explanation="Write did not report success; nothing to verify on disk.",
        )

    data = record.data
    if not isinstance(data, dict):
        return VerificationOutcome(
            verified=False,
            method="filesystem.content_match",
            explanation="Execution data is not a mapping; cannot locate written path.",
        )

    data = cast(dict[str, object], record.data)
    path_val: object = data.get("path")
    expected_val: object = data.get("content")
    if not isinstance(path_val, str) or not path_val:
        return VerificationOutcome(
            verified=False,
            method="filesystem.content_match",
            explanation="Execution data has no path string.",
        )
    path: str = path_val
    expected: str | None = expected_val if isinstance(expected_val, str) else None

    target = Path(path)
    if not target.is_file():
        return VerificationOutcome(
            verified=False,
            method="filesystem.stat",
            explanation=f"Expected file missing after write: {path!r}",
        )

    try:
        actual = target.read_text(encoding="utf-8")
    except OSError as exc:
        return VerificationOutcome(
            verified=False,
            method="filesystem.content_match",
            explanation=f"Could not re-read written file: {exc}",
        )

    if expected is not None and actual != expected:
        return VerificationOutcome(
            verified=False,
            method="filesystem.content_match",
            explanation="On-disk content does not match what the write reported.",
        )

    return VerificationOutcome(
        verified=True,
        method="filesystem.content_match",
        explanation=f"File {path!r} exists and content matches the write.",
    )


_READ_SCHEMA: dict[str, dict[str, object]] = {
    "path": {
        "type": "string",
        "required": True,
        "min_length": 1,
        "description": "Absolute path under an allowed filesystem root",
    },
}

_WRITE_SCHEMA: dict[str, dict[str, object]] = {
    "path": {
        "type": "string",
        "required": True,
        "min_length": 1,
        "description": "Absolute path under an allowed filesystem root",
    },
    "content": {
        "type": "string",
        "required": True,
        "description": "UTF-8 text to write",
    },
}


def register_filesystem_tools(
    registry: ToolRegistry,
    policy: FilesystemPolicy,
    *,
    verifier_registry: VerifierRegistry | None = None,
) -> None:
    registry.register(
        ToolDeclaration(
            name="filesystem.read",
            capabilities=frozenset({"filesystem.read"}),
            baseline_risk=RiskLevel.LOW,
            isolation_required=True,
            audit_required=True,
            description="Read a UTF-8 text file under allowed roots",
            argument_schema=_READ_SCHEMA,
        ),
        _read_handler(policy),
    )
    registry.register(
        ToolDeclaration(
            name="filesystem.write",
            capabilities=frozenset({"filesystem.write"}),
            baseline_risk=RiskLevel.HIGH,
            isolation_required=True,
            audit_required=True,
            description="Write a UTF-8 text file under allowed roots",
            argument_schema=_WRITE_SCHEMA,
        ),
        _write_handler(policy),
    )
    if verifier_registry is not None:
        verifier_registry.register("filesystem.write", filesystem_write_verifier)