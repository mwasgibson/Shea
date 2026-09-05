from __future__ import annotations

from types import TracebackType
from typing import Protocol


class UnitOfWork(Protocol):
    """A transaction boundary spanning more than one repository write.

    Phase 8 finding: `Orchestrator.advance()` persisted a Task's new
    state and recorded the audit event for that transition as two
    independently-committed writes. A crash between them left a state
    change with no corresponding audit record — a permanent gap in
    exactly the kind of security-relevant fact technical doc Section 18
    says must be reconstructable, and `SecurityService.enforce()`'s
    violation path had the same problem across three writes (violation
    audit, task state, transition audit).

    Implementations must be re-entrant: nested `with` blocks share one
    transaction, and only the outermost block actually commits or rolls
    back. This lets a repository wrap its own single write in `with
    self._uow: ...` for standalone use (unchanged behavior — commits
    immediately) while a caller composing several such writes wraps them
    all in one outer `with uow:` block to get one atomic transaction
    across the whole call graph, with no signature change needed on the
    individual `save()`/`record()` methods.
    """

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...