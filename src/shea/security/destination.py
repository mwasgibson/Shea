from __future__ import annotations

import ssl
import typing
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse


@dataclass(frozen=True)
class DestinationIdentity:
    """Research identity chain for one network hop.

    Requested URL
         ↓
    Canonical URL
         ↓
    Hostname
         ↓
    Resolved IP
         ↓
    TLS Peer (when HTTPS)
         ↓
    Final Destination (after redirects)
    """

    requested_url: str
    canonical_url: str
    hostname: str
    resolved_ip: str
    port: int
    scheme: str
    tls_peer_subject: str | None = None
    tls_peer_sans: tuple[str, ...] = ()
    tls_verified: bool | None = None
    redirect_index: int = 0

    def to_evidence(self) -> dict[str, Any]:
        return {
            "requested_url": self.requested_url,
            "canonical_url": self.canonical_url,
            "hostname": self.hostname,
            "resolved_ip": self.resolved_ip,
            "port": self.port,
            "scheme": self.scheme,
            "tls_peer_subject": self.tls_peer_subject,
            "tls_peer_sans": list(self.tls_peer_sans),
            "tls_verified": self.tls_verified,
            "redirect_index": self.redirect_index,
        }


def canonicalize_url(url: str) -> str:
    """Normalize scheme/host casing and default ports for stable comparison."""
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower()
    if not host:
        return url
    port = parsed.port
    if port is None:
        netloc = host
    elif (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        netloc = host
    else:
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def extract_tls_peer(sock: ssl.SSLSocket) -> tuple[str | None, tuple[str, ...], bool]:
    """Return (subject CN, SANs, verified) from an established TLS socket."""
    try:
        cert = sock.getpeercert()
    except Exception:
        return None, (), False
    if not cert:
        return None, (), False

    subject = None
    subject_data = typing.cast(tuple[tuple[tuple[str, str], ...], ...], cert.get("subject", ()))
    for rdn in subject_data:
        for item in rdn:
            if len(item) >= 2 and item[0] == "commonName":
                subject = str(item[1])
                break

    sans: list[str] = []
    san_data = typing.cast(tuple[tuple[str, str], ...], cert.get("subjectAltName", ()))
    for item in san_data:
        if len(item) >= 2:
            kind, value = item[0], item[1]
            if kind in {"DNS", "IP Address"}:
                sans.append(f"{kind}:{value}")

    return subject, tuple(sans), True



def build_identity(
    *,
    requested_url: str,
    hostname: str,
    resolved_ip: str,
    port: int,
    scheme: str,
    redirect_index: int = 0,
    tls_sock: ssl.SSLSocket | None = None,
) -> DestinationIdentity:
    subject: str | None = None
    sans: tuple[str, ...] = ()
    verified: bool | None = None
    if tls_sock is not None:
        subject, sans, verified = extract_tls_peer(tls_sock)
    return DestinationIdentity(
        requested_url=requested_url,
        canonical_url=canonicalize_url(requested_url),
        hostname=hostname,
        resolved_ip=resolved_ip,
        port=port,
        scheme=scheme,
        tls_peer_subject=subject,
        tls_peer_sans=sans,
        tls_verified=verified,
        redirect_index=redirect_index,
    )