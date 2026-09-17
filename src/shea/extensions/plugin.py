from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from shea.bootstrap import SheaRuntime


class SheaPlugin(Protocol):
    """Protocol for dynamic extensions to the Shea Runtime."""

    name: str
    version: str

    def register(self, runtime: SheaRuntime) -> None:
        """Called by the runtime during bootstrap to allow the plugin to hook in.
        
        Plugins can register new Tools, Adapters, Event listeners, or Memory handlers.
        """
        ...