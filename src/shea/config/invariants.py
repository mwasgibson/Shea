from __future__ import annotations

# Research doc Section 13.3's worked example:
#   System: allow_unsigned_plugins = false
#   Project: allow_unsigned_plugins = true
#   Effective: false
#
# Any key in this set can only ever be set at the SYSTEM layer; every
# other layer's value for that key is ignored by ConfigResolver, no
# matter how "more specific" it is. This is a starting set — later
# phases (Security, Extensions) should extend it as new invariants are
# identified, not silently rely on convention to keep values safe.
DEFAULT_SECURITY_INVARIANT_KEYS: frozenset[str] = frozenset(
    {
        "allow_unsigned_plugins",
        "sandbox_required",
        "external_content_can_authorize",  # must always resolve to False
        "max_tool_privilege_level",
    }
)