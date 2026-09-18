from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shea.bootstrap import SheaRuntime
from shea.events.bus import EventBus
from shea.events.contracts import Event
from shea.security.exceptions import SecurityViolationError
from shea.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class RestrictedToolRegistry:
    def __init__(self, original: ToolRegistry, plugin_name: str, allowed: bool):
        self._original = original
        self._plugin_name = plugin_name
        self._allowed = allowed

    def register(self, *args: Any, **kwargs: Any) -> None:
        if not self._allowed:
            raise SecurityViolationError("core", "extensions", f"Plugin '{self._plugin_name}' is not allowed to register tools.")
        self._original.register(*args, **kwargs)
        
    def get_declaration(self, name: str) -> Any:
        return self._original.get_declaration(name)
        
    def get_handler(self, name: str) -> Any:
        return self._original.get_handler(name)
        
    def list_tools(self) -> list[Any]:
        return self._original.list_tools()


class RestrictedEventBus:
    def __init__(self, original: EventBus, plugin_name: str, can_publish: bool, can_subscribe: bool):
        self._original = original
        self._plugin_name = plugin_name
        self._can_publish = can_publish
        self._can_subscribe = can_subscribe

    def publish(self, event: Event) -> None:
        if not self._can_publish:
            raise SecurityViolationError("core", "extensions", f"Plugin '{self._plugin_name}' is not allowed to publish events.")
        # Ensure plugin marks itself as source
        if event.source != f"plugin.{self._plugin_name}":
            event = Event(
                event_id=event.event_id,
                event_type=event.event_type,
                source=f"plugin.{self._plugin_name}",
                timestamp=event.timestamp,
                payload=event.payload,
                correlation_id=event.correlation_id
            )
        self._original.publish(event)

    def subscribe(self, pattern: str, handler: Callable[[Event], None]) -> str:
        if not self._can_subscribe:
            raise SecurityViolationError("core", "extensions", f"Plugin '{self._plugin_name}' is not allowed to subscribe to events.")
        return self._original.subscribe(pattern, handler)

    def unsubscribe(self, subscription_id: str) -> None:
        self._original.unsubscribe(subscription_id)


class RestrictedRuntimeProxy:
    """A proxy over SheaRuntime that restricts access based on a security manifest."""
    
    def __init__(self, runtime: SheaRuntime, plugin_name: str, manifest: dict[str, Any]):
        self._runtime = runtime
        self._plugin_name = plugin_name
        self._manifest = manifest
        
        permissions = manifest.get("permissions", [])
        
        # Tools permission
        self.tool_registry = RestrictedToolRegistry(
            runtime.tool_registry, 
            plugin_name, 
            "tools.register" in permissions
        )
        
        # Events permission
        self.event_bus = RestrictedEventBus(
            runtime.event_bus,
            plugin_name,
            "events.publish" in permissions,
            "events.subscribe" in permissions
        )
        
    # Block access to deeply sensitive components by raising errors if accessed
    @property
    def credential_broker(self) -> Any:
        raise SecurityViolationError("core", "extensions", f"Plugin '{self._plugin_name}' cannot access credentials directly.")
        
    @property
    def decision_service(self) -> Any:
        raise SecurityViolationError("core", "extensions", f"Plugin '{self._plugin_name}' cannot bypass the decision engine.")
        
    @property
    def security_gate(self) -> Any:
        raise SecurityViolationError("core", "extensions", f"Plugin '{self._plugin_name}' cannot access the security gate.")

    @property
    def memory_extractor(self) -> Any:
        raise SecurityViolationError("core", "extensions", f"Plugin '{self._plugin_name}' cannot access memory extractor.")
        
    @property
    def profile_service(self) -> Any:
        raise SecurityViolationError("core", "extensions", f"Plugin '{self._plugin_name}' cannot access profile service.")
