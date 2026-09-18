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
        
        Note: The runtime passed here may be a RestrictedRuntimeProxy enforcing
        permissions declared in the plugin's security manifest.
        """
        ...