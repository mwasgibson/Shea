from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from shea.security.exceptions import SecurityViolationError
from shea.security.network_policy import NetworkPolicy, is_url_allowed


@dataclass(frozen=True)
class ProxyDecision:
    mode: str  # "direct" | "proxy"
    proxy_url: str | None = None


def decide_proxy(
    *,
    allow_proxy: bool,
    proxy_url: str | None,
    target_url: str,
    policy: NetworkPolicy,
    tool: str = "network",
) -> ProxyDecision:
    """Fail-closed proxy policy.

    - allow_proxy False → always direct; any configured proxy_url is ignored/denied
    - allow_proxy True requires non-empty proxy_url that itself passes URL policy
    - Proxy host cannot be private if block_private_networks
    """
    if not allow_proxy:
        if proxy_url:
            raise SecurityViolationError(
                tool,
                "network",
                "proxy_url set but allow_proxy is False",
            )
        return ProxyDecision(mode="direct")

    if not proxy_url:
        raise SecurityViolationError(
            tool, "network", "allow_proxy True but proxy_url missing"
        )

    parsed = urlparse(proxy_url)
    if parsed.scheme not in {"http", "https", "socks5"}:
        raise SecurityViolationError(
            tool, "network", f"unsupported proxy scheme: {parsed.scheme!r}"
        )
    if not parsed.hostname:
        raise SecurityViolationError(tool, "network", "proxy_url missing host")

    # Reuse host policy against the proxy endpoint itself
    if not is_url_allowed(proxy_url, policy):
        raise SecurityViolationError(
            tool, "network", f"proxy endpoint blocked by policy: {proxy_url!r}"
        )

    # Target still must be allowed independently
    if not is_url_allowed(target_url, policy):
        raise SecurityViolationError(
            tool, "network", f"target blocked by policy: {target_url!r}"
        )

    return ProxyDecision(mode="proxy", proxy_url=proxy_url)