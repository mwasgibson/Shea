from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from typing import NamedTuple, cast
from urllib.parse import urlparse

from shea.security.exceptions import SecurityViolationError
from shea.security.filesystem_policy import FilesystemPolicy, is_path_allowed
from shea.security.network_policy import NetworkPolicy, is_url_allowed


class ResolvedUrl(NamedTuple):
    """A URL that has been DNS-resolved and policy-checked.

    Holds the original URL string, the resolved host and port to which
    the connection must be pinned (to close the DNS-rebinding TOCTOU gap),
    and the canonical hostname to use for the Host header and TLS SNI.
    """

    url: str
    host: str
    port: int
    resolved_ip: str


def resolve_and_check_url(
    url: str, policy: NetworkPolicy, *, tool: str = "network"
) -> ResolvedUrl:
    """DNS-resolve host and re-check every address against network policy.

    Closes the pure-policy gap: ``is_url_allowed`` only inspects the host
    string. This resolves DNS at access time and blocks private /
    loopback / link-local / reserved / multicast results when
    ``policy.block_private_networks`` is True.

    Returns a ResolvedUrl that pins the connection to the resolved IP
    (preventing DNS-rebinding TOCTOU): the caller must connect to
    resolved_ip:port while sending the original host as the Host header
    and TLS SNI.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise SecurityViolationError(tool, "network", f"URL has no host: {url!r}")

    if not is_url_allowed(url, policy):
        raise SecurityViolationError(tool, "network", f"URL blocked by policy: {url!r}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SecurityViolationError(
            tool, "network", f"DNS resolution failed: {exc}"
        ) from exc

    if not infos:
        raise SecurityViolationError(
            tool, "network", f"DNS resolution returned no addresses for {host!r}"
        )

    if policy.block_private_networks:
        for info in infos:
            ip_str = info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                raise SecurityViolationError(
                    tool,
                    "network",
                    f"Resolved address {ip_str} for host {host!r} is not publicly routable",
                )

    # Return the first resolved address to pin the connection.
    # Using the first address matches typical client behavior and
    # ensures we connect to an IP we actually validated.
    resolved_ip: str = cast(str, infos[0][4][0])
    return ResolvedUrl(url=url, host=host, port=port, resolved_ip=resolved_ip)


def realpath_under_roots(
    path: str, policy: FilesystemPolicy, *, tool: str = "filesystem"
) -> Path:
    """Resolve symlinks and require the real path stay under an allowed root.

    Closes the pure-policy gap: ``is_path_allowed`` is logical normalization
    only. This touches the filesystem via ``Path.resolve()`` so a symlink
    inside an allowed root that points outside is rejected.
    """
    if not is_path_allowed(path, policy):
        raise SecurityViolationError(
            tool, "filesystem", f"Path blocked by policy: {path!r}"
        )

    real = Path(path).resolve()
    for root in policy.allowed_roots:
        root_real = Path(root).resolve()
        try:
            real.relative_to(root_real)
            return real
        except ValueError:
            continue
    raise SecurityViolationError(
        tool,
        "filesystem",
        f"Resolved path {str(real)!r} escapes allowed roots",
    )