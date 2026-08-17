from __future__ import annotations

from typing import Protocol


class IdGenerator(Protocol):
    """Identifier generation as an injectable dependency, for the same
    testability reason as Clock — tests use a sequential generator so
    assertions don't depend on random UUIDs.
    """

    def new_id(self) -> str: ...