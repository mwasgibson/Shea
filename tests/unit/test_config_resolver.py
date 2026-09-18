from shea.config.invariants import DEFAULT_SECURITY_INVARIANT_KEYS
from shea.config.layers import ConfigLayer
from shea.config.resolver import ConfigResolver


def test_config_layer_precedence():
    resolver = ConfigResolver()
    
    # Layer 1: Machine
    resolver.set_layer_value(ConfigLayer.MACHINE, "API_URL", "http://machine.local")
    
    # Layer 2: User
    resolver.set_layer_value(ConfigLayer.USER, "API_URL", "http://user.local")
    
    # Layer 3: Session (highest precedence in this test)
    resolver.set_layer_value(ConfigLayer.SESSION, "API_URL", "http://session.local")
    
    assert resolver.resolve("API_URL") == "http://session.local"
    
def test_config_security_invariant():
    resolver = ConfigResolver()
    
    # "allow_unsafe_execution" is in DEFAULT_SECURITY_INVARIANT_KEYS (usually)
    # Let's just use whatever is in the set
    if not DEFAULT_SECURITY_INVARIANT_KEYS:
        return
        
    sec_key = list(DEFAULT_SECURITY_INVARIANT_KEYS)[0]
    
    resolver.set_layer_value(ConfigLayer.SYSTEM, sec_key, "system_enforced")
    
    # A user tries to override the security invariant
    resolver.set_layer_value(ConfigLayer.SESSION, sec_key, "malicious_override")
    
    # Resolver MUST ignore the session and return the SYSTEM layer
    assert resolver.resolve(sec_key) == "system_enforced"
    
    # Effective config should also enforce it
    eff = resolver.effective_config()
    assert eff[sec_key] == "system_enforced"
