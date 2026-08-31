from __future__ import annotations

import posixpath
from dataclasses import dataclass


@dataclass(frozen=True)
class FilesystemPolicy:
    """Deterministic filesystem scope policy — research doc Section 10.6:
    "A plugin that needs ~/Projects/example shouldn't automatically get /."

    KNOWN LIMITATION: this is pure logical path normalization, not a
    filesystem-aware check. It does not touch disk and does not resolve
    symlinks, so a symlink inside an allowed root that points outside it
    will not be caught here — that requires an OS-level realpath check at
    actual access time, which belongs in the real execution/sandbox
    layer, not this pure policy function.
    """

    allowed_roots: frozenset[str]


def is_path_allowed(path: str, policy: FilesystemPolicy) -> bool:
    normalized = posixpath.normpath(path)
    if not posixpath.isabs(normalized):
        return False

    for root in policy.allowed_roots:
        normalized_root = posixpath.normpath(root)
        if normalized == normalized_root or normalized.startswith(normalized_root + "/"):
            return True
    return False