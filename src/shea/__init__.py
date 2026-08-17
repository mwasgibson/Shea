"""SHEA — Phase 1 core runtime.

This package contains only the foundation layer described in the Phase 1
milestone: typed contracts, the task state machine, SQLite persistence,
layered configuration, and the thin orchestrator that wires them together.

No model, tool, policy, or risk logic lives here yet — those subsystems
plug into the ports defined in `shea.ports` in later phases, without
requiring changes to this layer.
"""

__version__ = "0.1.0"