from __future__ import annotations

import shutil
from pathlib import Path

from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.app.ports.process import AdapterContext
from shea.security.exceptions import SecurityViolationError
from shea.security.filesystem_policy import FilesystemPolicy
from shea.security.runtime_checks import realpath_under_roots

_READ_OPS = frozenset({"filesystem.inspect", "filesystem.read"})
_WRITE_OPS = frozenset({
    "filesystem.write",
    "filesystem.create",
    "filesystem.delete",
    "filesystem.copy",
    "filesystem.move",
})


class LocalFilesystemAdapter:
    """V1 filesystem adapter: canonical realpath, scope roots, postconditions."""

    name = "filesystem.local"

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.operation.startswith("filesystem.") or contract.capability in {
            "filesystem.read",
            "filesystem.write",
        }

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        raw_ctx = contract.metadata.get("_adapter_context")
        ctx: AdapterContext | None = (
            raw_ctx if isinstance(raw_ctx, AdapterContext) else None
        )
        if ctx is None:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="filesystem.local requires scope + AdapterContext",
                evidence=self._base_evidence(receipt, attempt),
            )

        fs_scope = ctx.scope.filesystem
        if not fs_scope.allowed_roots:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="filesystem scope allowed_roots is empty; refusing access",
                evidence=self._base_evidence(receipt, attempt),
            )

        if contract.operation in _WRITE_OPS and fs_scope.read_only:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="filesystem scope is read_only",
                evidence=self._base_evidence(receipt, attempt),
            )

        path_arg = contract.arguments.get("path")
        if not isinstance(path_arg, str) or not path_arg:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="arguments.path must be a non-empty str",
                evidence=self._base_evidence(receipt, attempt),
            )

        policy = FilesystemPolicy(allowed_roots=fs_scope.allowed_roots)
        try:
            real = realpath_under_roots(path_arg, policy, tool="filesystem.local")
        except SecurityViolationError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence=self._base_evidence(receipt, attempt),
            )

        op = contract.operation
        if op in {"filesystem.copy", "filesystem.move"}:
            destination_arg = contract.arguments.get("destination")
            if not isinstance(destination_arg, str) or not destination_arg:
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error="arguments.destination must be a non-empty str",
                    evidence=self._base_evidence(receipt, attempt),
                )
            try:
                destination = realpath_under_roots(
                    destination_arg, policy, tool="filesystem.local"
                )
            except SecurityViolationError as exc:
                return AdapterResult(
                    outcome=AppOutcome.FAILURE,
                    error=str(exc),
                    evidence=self._base_evidence(receipt, attempt),
                )
            if op == "filesystem.copy":
                return self._copy(real, destination, receipt, attempt)
            return self._move(real, destination, receipt, attempt)
        if op == "filesystem.inspect":
            return self._inspect(real, receipt, attempt)
        if op == "filesystem.read":
            return self._read(real, receipt, attempt)
        if op == "filesystem.write":
            return self._write(real, contract, receipt, attempt)
        if op == "filesystem.create":
            return self._create(real, contract, receipt, attempt)
        if op == "filesystem.delete":
            return self._delete(real, receipt, attempt)

        return AdapterResult(
            outcome=AppOutcome.FAILURE,
            error=f"unsupported filesystem operation: {op!r}",
            evidence=self._base_evidence(receipt, attempt),
        )

    def _copy(
        self,
        source: Path,
        destination: Path,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        if not source.is_file():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"not a file: {source}",
                evidence={**self._base_evidence(receipt, attempt), "path": str(source)},
            )
        if destination.exists():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"destination already exists: {destination}",
                evidence={
                    **self._base_evidence(receipt, attempt),
                    "path": str(source),
                    "destination": str(destination),
                },
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence={
                    **self._base_evidence(receipt, attempt),
                    "path": str(source),
                    "destination": str(destination),
                },
            )
        if not destination.is_file() or not source.is_file():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="postcondition failed: source or destination missing after copy",
                evidence={
                    **self._base_evidence(receipt, attempt),
                    "path": str(source),
                    "destination": str(destination),
                },
            )
        elif source.stat().st_size != destination.stat().st_size:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="postcondition failed: size mismatch after copy",
                evidence={
                    **self._base_evidence(receipt, attempt),
                    "path": str(source),
                    "destination": str(destination),
                },
            )
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base_evidence(receipt, attempt),
                "path": str(source),
                "destination": str(destination),
                "copied": True,
                "postcondition": "source_and_destination_exist",
            },
        )

    def _move(
        self,
        source: Path,
        destination: Path,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        if not source.is_file():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"not a file: {source}",
                evidence={**self._base_evidence(receipt, attempt), "path": str(source)},
            )
        if source.resolve() == destination.resolve():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="source and destination are the same path",
                evidence={
                    **self._base_evidence(receipt, attempt),
                    "path": str(source),
                    "destination": str(destination),
                },
            )
        if destination.exists():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"destination already exists: {destination}",
                evidence={
                    **self._base_evidence(receipt, attempt),
                    "path": str(source),
                    "destination": str(destination),
                },
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(destination))
        except OSError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence={
                    **self._base_evidence(receipt, attempt),
                    "path": str(source),
                    "destination": str(destination),
                },
            )
        if source.exists() or not destination.is_file():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="postcondition failed: source or destination state after move",
                evidence={
                    **self._base_evidence(receipt, attempt),
                    "path": str(source),
                    "destination": str(destination),
                },
            )
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base_evidence(receipt, attempt),
                "path": str(source),
                "destination": str(destination),
                "moved": True,
                "postcondition": "source_absent_destination_exists",
            },
        )

    def _inspect(
        self, path: Path, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> AdapterResult:
        exists = path.exists()
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base_evidence(receipt, attempt),
                "path": str(path),
                "exists": exists,
                "is_file": path.is_file() if exists else False,
                "is_dir": path.is_dir() if exists else False,
                "size": path.stat().st_size if exists and path.is_file() else None,
            },
        )

    def _read(
        self, path: Path, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> AdapterResult:
        if not path.is_file():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"not a file: {path}",
                evidence={**self._base_evidence(receipt, attempt), "path": str(path)},
            )
        content = path.read_text(encoding="utf-8")
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base_evidence(receipt, attempt),
                "path": str(path),
                "content": content,
                "size": len(content.encode("utf-8")),
            },
        )

    def _write(
        self,
        path: Path,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        content = contract.arguments.get("content")
        if not isinstance(content, str):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="arguments.content must be str",
                evidence=self._base_evidence(receipt, attempt),
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        # Postcondition: independent read-back
        if not path.is_file():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="postcondition failed: file missing after write",
                evidence={**self._base_evidence(receipt, attempt), "path": str(path)},
            )
        observed = path.read_text(encoding="utf-8")
        if observed != content:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="postcondition failed: content mismatch after write",
                evidence={**self._base_evidence(receipt, attempt), "path": str(path)},
            )
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base_evidence(receipt, attempt),
                "path": str(path),
                "content": content,
                "bytes_written": len(content.encode("utf-8")),
                "postcondition": "content_match",
            },
        )

    def _create(
        self,
        path: Path,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        if path.exists():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"already exists: {path}",
                evidence={**self._base_evidence(receipt, attempt), "path": str(path)},
            )
        content = contract.arguments.get("content", "")
        if not isinstance(content, str):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="arguments.content must be str",
                evidence=self._base_evidence(receipt, attempt),
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if not path.is_file():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="postcondition failed: file missing after create",
                evidence={**self._base_evidence(receipt, attempt), "path": str(path)},
            )
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base_evidence(receipt, attempt),
                "path": str(path),
                "created": True,
                "postcondition": "exists",
            },
        )

    def _delete(
        self, path: Path, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> AdapterResult:
        if not path.exists():
            return AdapterResult(
                outcome=AppOutcome.SUCCESS,
                evidence={
                    **self._base_evidence(receipt, attempt),
                    "path": str(path),
                    "deleted": False,
                    "note": "already absent",
                },
            )
        if path.is_dir():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="refusing to delete directory in V1",
                evidence={**self._base_evidence(receipt, attempt), "path": str(path)},
            )
        path.unlink()
        if path.exists():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="postcondition failed: path still exists after delete",
                evidence={**self._base_evidence(receipt, attempt), "path": str(path)},
            )
        return AdapterResult(
            outcome=AppOutcome.SUCCESS,
            evidence={
                **self._base_evidence(receipt, attempt),
                "path": str(path),
                "deleted": True,
                "postcondition": "absent",
            },
        )

    def _base_evidence(
        self, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> dict[str, str]:
        return {"receipt_id": receipt.id, "attempt_id": attempt.id}