from __future__ import annotations

from unittest.mock import patch

from shea.security.network_policy import NetworkPolicy
from shea.security.runtime_checks import ResolvedUrl, resolve_and_check_url


def test_resolve_and_check_url_returns_resolved_ip() -> None:
    """Test that resolve_and_check_url returns the resolved IP address."""
    policy = NetworkPolicy(block_private_networks=True)
    
    # Mock DNS resolution to return a specific IP
    fake_info = [(None, None, None, None, ("93.184.216.34", 80))]
    
    with patch("shea.security.runtime_checks.socket.getaddrinfo", return_value=fake_info):
        result = resolve_and_check_url("http://example.com/", policy)
        
        assert isinstance(result, ResolvedUrl)
        assert result.url == "http://example.com/"
        assert result.host == "example.com"
        assert result.port == 80
        assert result.resolved_ip == "93.184.216.34"
        
    print("✓ resolve_and_check_url returns ResolvedUrl with resolved IP")


def test_resolve_and_check_url_https_default_port() -> None:
    """Test that HTTPS URLs get port 443 by default."""
    policy = NetworkPolicy(block_private_networks=True)
    
    fake_info = [(None, None, None, None, ("93.184.216.34", 443))]
    
    with patch("shea.security.runtime_checks.socket.getaddrinfo", return_value=fake_info):
        result = resolve_and_check_url("https://example.com/", policy)
        
        assert result.port == 443
        
    print("✓ HTTPS URLs default to port 443")


def test_resolve_and_check_url_custom_port() -> None:
    """Test that custom ports are preserved."""
    policy = NetworkPolicy(block_private_networks=True)
    
    fake_info = [(None, None, None, None, ("93.184.216.34", 8080))]
    
    with patch("shea.security.runtime_checks.socket.getaddrinfo", return_value=fake_info):
        result = resolve_and_check_url("http://example.com:8080/", policy)
        
        assert result.port == 8080
        
    print("✓ Custom ports are preserved")


def test_resolve_and_check_url_blocks_private_ips() -> None:
    """Test that private IPs are blocked when policy requires it."""
    from shea.security.exceptions import SecurityViolationError
    
    policy = NetworkPolicy(block_private_networks=True)
    
    # Mock DNS to return a private IP
    fake_info = [(None, None, None, None, ("127.0.0.1", 80))]
    
    with patch("shea.security.runtime_checks.socket.getaddrinfo", return_value=fake_info):
        try:
            resolve_and_check_url("http://example.com/", policy)
            raise AssertionError("Expected SecurityViolationError")
        except SecurityViolationError as e:
            assert "not publicly routable" in str(e)
        
    print("✓ Private IPs are blocked when policy requires")


if __name__ == "__main__":
    test_resolve_and_check_url_returns_resolved_ip()
    test_resolve_and_check_url_https_default_port()
    test_resolve_and_check_url_custom_port()
    test_resolve_and_check_url_blocks_private_ips()
    print("\nAll DNS-pinning tests passed!")