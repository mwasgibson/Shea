from unittest.mock import MagicMock

import pytest

from shea.events.contracts import Event
from shea.extensions.security import RestrictedRuntimeProxy
from shea.security.exceptions import SecurityViolationError


def test_plugin_zero_permissions():
    runtime_mock = MagicMock()
    manifest = {"permissions": []}
    
    proxy = RestrictedRuntimeProxy(runtime_mock, "evil_plugin", manifest)
    
    with pytest.raises(SecurityViolationError, match="not allowed to register tools"):
        proxy.tool_registry.register(tool_name="hack", description="hack", schema={}, handler=lambda x: None)
        
    with pytest.raises(SecurityViolationError, match="not allowed to publish events"):
        proxy.event_bus.publish(Event(event_id="1", event_type="test", source="test", timestamp=MagicMock(), payload={}, correlation_id="1"))
        
    with pytest.raises(SecurityViolationError, match="cannot access credentials directly"):
        _ = proxy.credential_broker
        
def test_plugin_with_permissions():
    runtime_mock = MagicMock()
    manifest = {"permissions": ["tools.register", "events.publish"]}
    
    proxy = RestrictedRuntimeProxy(runtime_mock, "good_plugin", manifest)
    
    # Should not raise
    proxy.tool_registry.register(tool_name="my_tool", description="tool", schema={}, handler=lambda x: None)
    
    # Check that it proxies to the original registry
    runtime_mock.tool_registry.register.assert_called_once()
    
    # Event publishing should overwrite source
    event = Event(event_id="1", event_type="test", source="fake_source", timestamp=MagicMock(), payload={}, correlation_id="1")
    proxy.event_bus.publish(event)
    
    published_event = runtime_mock.event_bus.publish.call_args[0][0]
    assert published_event.source == "plugin.good_plugin"
