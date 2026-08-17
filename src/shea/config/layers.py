from __future__ import annotations

from enum import StrEnum


class ConfigLayer(StrEnum):
    """Research doc Section 13.2: System -> Machine -> User -> Profile ->
    Project -> Session. More specific layers generally override broader
    ones — "generally" because security-invariant keys are the deliberate
    exception (Section 13.3), handled in resolver.py, not here.
    """

    SYSTEM = "system"
    MACHINE = "machine"
    USER = "user"
    PROFILE = "profile"
    PROJECT = "project"
    SESSION = "session"


# Most-specific-first: this is the order resolver.py walks when looking
# up a single key's effective value.
LAYER_PRECEDENCE: tuple[ConfigLayer, ...] = (
    ConfigLayer.SESSION,
    ConfigLayer.PROJECT,
    ConfigLayer.PROFILE,
    ConfigLayer.USER,
    ConfigLayer.MACHINE,
    ConfigLayer.SYSTEM,
)