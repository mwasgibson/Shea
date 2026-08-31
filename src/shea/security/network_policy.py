from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from urllib.parse import urlparse

# Research doc Section 11.8's explicit named example beyond IP literals.
DEFAULT_BLOCKED_HOSTNAMES: frozenset[str] = frozenset({"localhost", "metadata.google.internal"})


@dataclass(frozen=True)
class NetworkPolicy:
    """Deterministic SSRF protection policy.

    `allowed_hosts=None` means blocklist mode: any host not caught by
    `blocked_hostnames` or the private/loopback/link-local/reserved IP
    checks is allowed. Supplying a non-None `allowed_hosts` set switches
    to allow-list mode, where only those exact hosts are permitted —
    strictly more restrictive, and the blocklist becomes irrelevant since
    nothing outside the allow-list passes anyway.
    """

    allowed_hosts: frozenset[str] | None = None
    blocked_hostnames: frozenset[str] = field(default_factory=lambda: DEFAULT_BLOCKED_HOSTNAMES)
    block_private_networks: bool = True


def _is_blocked_ip_literal(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def is_url_allowed(url: str, policy: NetworkPolicy | None = None) -> bool:
    """Research doc Section 11.8: block requests to localhost, private
    networks, and the cloud metadata endpoint (169.254.169.254 falls
    under `is_link_local`) unless explicitly allow-listed.

    KNOWN LIMITATION: this checks the literal host string in the URL, not
    what that host resolves to. A hostname that resolves to a private
    address at request time (DNS rebinding) is not caught here — that
    requires resolving DNS at the moment of the actual network call,
    which belongs in the real execution/sandbox layer, not this pure
    policy function.
    """
    active_policy = policy or NetworkPolicy()
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False

    if active_policy.allowed_hosts is not None:
        return host in active_policy.allowed_hosts

    if host.lower() in active_policy.blocked_hostnames:
        return False

    if active_policy.block_private_networks and _is_blocked_ip_literal(host):
        return False

    return True