from __future__ import annotations

import ipaddress

from hypothesis import given
from hypothesis import strategies as st

from shea.security.filesystem_policy import FilesystemPolicy, is_path_allowed
from shea.security.network_policy import NetworkPolicy, is_url_allowed

private_ipv4 = st.one_of(
    st.integers(min_value=0, max_value=255).map(lambda b: f"127.{b}.0.1"),
    st.integers(min_value=0, max_value=255).map(lambda b: f"10.{b}.0.1"),
    st.integers(min_value=16, max_value=31).map(lambda b: f"172.{b}.0.1"),
    st.integers(min_value=0, max_value=255).map(lambda b: f"192.168.{b}.1"),
    st.integers(min_value=0, max_value=255).map(lambda b: f"169.254.{b}.1"),
)


@given(host=private_ipv4)
def test_private_and_link_local_ip_literals_are_always_blocked(host: str) -> None:
    """Every generated loopback/private/link-local IPv4 literal must be
    blocked in default (blocklist) mode, regardless of scheme or path —
    the SSRF check must not have gaps for specific octet values.
    """
    assert is_url_allowed(f"http://{host}/") is False
    assert is_url_allowed(f"https://{host}:8443/some/path") is False


@given(a=st.integers(1, 223), b=st.integers(0, 255), c=st.integers(0, 255), d=st.integers(1, 254))
def test_public_looking_ips_outside_reserved_ranges_are_allowed(
    a: int, b: int, c: int, d: int
) -> None:
    """Sanity check in the other direction: addresses outside every
    IANA special-use range are not blocked by `block_private_networks`.

    Previously hand-maintained a partial exclusion list (10.x, 127.x,
    169.254.x, 172.16-31.x, 192.168.x) that Hypothesis eventually found a
    gap in: 192.0.0.0/24 (IETF Protocol Assignments, RFC 6890) is a real
    special-use range that `_is_blocked_ip_literal` correctly blocks, but
    the old list never excluded it, so the property assertion itself was
    wrong. There are several more such ranges (100.64.0.0/10, 192.0.2.0/24,
    198.18.0.0/15, 203.0.113.0/24, and others) that a hand-maintained list
    would need to track and could drift from again. Deriving the skip
    condition from `ipaddress` directly — the same classification
    `_is_blocked_ip_literal` itself uses — means this test can't drift out
    of sync with what the policy actually blocks.
    """
    host = f"{a}.{b}.{c}.{d}"
    address = ipaddress.ip_address(host)
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return
    assert is_url_allowed(f"http://{host}/") is True


@given(
    filename=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")), min_size=1, max_size=12
    )
)
def test_paths_under_allowed_root_are_always_allowed(filename: str) -> None:
    policy = FilesystemPolicy(allowed_roots=frozenset({"/workspace"}))
    assert is_path_allowed(f"/workspace/{filename}", policy) is True


@given(
    other_root=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")), min_size=1, max_size=12
    )
)
def test_paths_outside_any_allowed_root_are_always_blocked(other_root: str) -> None:
    policy = FilesystemPolicy(allowed_roots=frozenset({"/workspace"}))
    candidate = f"/{other_root}/file.txt"
    if candidate.startswith("/workspace/") or candidate == "/workspace":
        return
    assert is_path_allowed(candidate, policy) is False


def test_network_policy_default_construction_never_raises() -> None:
    NetworkPolicy()  # must not raise