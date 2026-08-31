from __future__ import annotations

import pytest

from shea.security.network_policy import NetworkPolicy, is_url_allowed


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_dangerous_targets_are_blocked(url: str) -> None:
    assert is_url_allowed(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1/weather",
        "https://8.8.8.8/",
        "http://93.184.216.34/",
    ],
)
def test_ordinary_public_targets_are_allowed(url: str) -> None:
    assert is_url_allowed(url) is True


def test_url_with_no_host_is_blocked() -> None:
    assert is_url_allowed("not-a-url") is False


def test_allow_list_mode_only_permits_listed_hosts() -> None:
    policy = NetworkPolicy(allowed_hosts=frozenset({"api.example.com"}))

    assert is_url_allowed("https://api.example.com/x", policy) is True
    assert is_url_allowed("https://evil.example.com/x", policy) is False


def test_allow_list_mode_overrides_blocklist_absence_check() -> None:
    """Allow-list mode is strictly narrower than blocklist mode: even a
    host that isn't in the default blocked hostnames is rejected if it's
    not explicitly on the allow-list.
    """
    policy = NetworkPolicy(allowed_hosts=frozenset({"api.example.com"}))
    assert is_url_allowed("https://totally-fine-looking.com/", policy) is False


def test_block_private_networks_can_be_disabled() -> None:
    policy = NetworkPolicy(block_private_networks=False)
    assert is_url_allowed("http://10.0.0.5/", policy) is True


def test_custom_blocked_hostnames() -> None:
    policy = NetworkPolicy(blocked_hostnames=frozenset({"internal.corp"}))
    assert is_url_allowed("http://internal.corp/", policy) is False
    assert is_url_allowed("http://localhost/", policy) is True  # not in custom set