from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from shea.app.contracts import ExecutionAttempt, ExecutionReceipt
from shea.app.enums import AppOutcome
from shea.app.reconcile.base import ReconcileObservation


class FilesystemReconciler:
    """Reconcile filesystem.* by path existence / content probes only."""

    name = "filesystem"

    def supports(self, receipt: ExecutionReceipt) -> bool:
        op = receipt.operation or ""
        return op.startswith("filesystem.") or (receipt.capability or "").startswith(
            "filesystem."
        )

    def observe(
        self,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt | None,
        *,
        stuck_reason: str,
    ) -> ReconcileObservation:
        # Never re-write. Only read.
        path = self._path_from(receipt, attempt)
        if path is None:
            return ReconcileObservation(
                outcome=AppOutcome.UNKNOWN,
                detail=f"{stuck_reason}; no path in receipt/attempt evidence",
            )

        op = receipt.operation or ""
        exists = path.exists()

        if "write" in op or "create" in op or op.endswith(".write"):
            if exists and path.is_file():
                return ReconcileObservation(
                    outcome=AppOutcome.SUCCESS,
                    detail="write postcondition: path exists as file",
                    evidence={"path": str(path), "exists": True},
                    side_effect_detected=True,
                )
            if stuck_reason == "attempt_invoked_not_finalized":
                return ReconcileObservation(
                    outcome=AppOutcome.UNKNOWN,
                    detail="write may or may not have completed; path absent",
                    evidence={"path": str(path), "exists": False},
                )
            return ReconcileObservation(
                outcome=AppOutcome.FAILURE,
                detail="write never reached invoke or left no file",
                evidence={"path": str(path), "exists": False},
            )

        if "delete" in op or "unlink" in op:
            if not exists:
                return ReconcileObservation(
                    outcome=AppOutcome.SUCCESS,
                    detail="delete postcondition: path absent",
                    evidence={"path": str(path), "exists": False},
                    side_effect_detected=True,
                )
            if stuck_reason == "attempt_invoked_not_finalized":
                return ReconcileObservation(
                    outcome=AppOutcome.UNKNOWN,
                    detail="delete may have failed; path still present",
                    evidence={"path": str(path), "exists": True},
                    side_effect_detected=False,
                )
            return ReconcileObservation(
                outcome=AppOutcome.FAILURE,
                detail="delete did not remove path",
                evidence={"path": str(path), "exists": True},
            )

        if "read" in op:
            # Read has no durable side effect; if never finalized → FAILURE
            if stuck_reason == "attempt_invoked_not_finalized":
                return ReconcileObservation(
                    outcome=AppOutcome.UNKNOWN,
                    detail="read invoke may have completed without finalize",
                    evidence={"path": str(path), "exists": exists},
                )
            return ReconcileObservation(
                outcome=AppOutcome.FAILURE,
                detail="read never completed",
                evidence={"path": str(path)},
            )

        return ReconcileObservation(
            outcome=AppOutcome.UNKNOWN,
            detail=f"no filesystem observation rule for {op!r}",
            evidence={"path": str(path)},
        )

    def _path_from(
        self, receipt: ExecutionReceipt, attempt: ExecutionAttempt | None
    ) -> Path | None:
        for source in (
            (attempt.evidence if attempt else {}) or {},
            receipt.metadata or {},
        ):
            raw = source.get("path") or source.get("target_path")
            if isinstance(raw, str) and raw:
                try:
                    return Path(raw).resolve()
                except OSError:
                    return Path(raw)
        # tool plane: arguments often in metadata
        args = (receipt.metadata or {}).get("arguments")
        if isinstance(args, dict):
            args = cast(dict[str, Any], args)
            raw = args.get("path")
            if isinstance(raw, str) and raw:
                return Path(raw)
        return None