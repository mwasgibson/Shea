from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

from shea.security.exceptions import SecurityViolationError
from shea.security.filesystem_policy import FilesystemPolicy, is_path_allowed
from shea.security.network_policy import NetworkPolicy, is_url_allowed


def resolve_and_check_url(
    url: str, policy: NetworkPolicy, *, tool: str = "network"
) -> str:
    """DNS-resolve host and re-check every address against network policy.

    Closes the pure-policy gap: ``is_url_allowed`` only inspects the host
    string. This resolves DNS at access time and blocks private /
    loopback / link-local / reserved / multicast results when
    ``policy.block_private_networks`` is True.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise SecurityViolationError(tool, "network", f"URL has no host: {url!r}")

    if not is_url_allowed(url, policy):
        raise SecurityViolationError(tool, "network", f"URL blocked by policy: {url!r}")

    try:
        infos = socket.getaddrinfo(host, parsed.port or 80, type=socket.SOCK_STREAM)
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
    return url


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