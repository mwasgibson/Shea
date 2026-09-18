from __future__ import annotations

import base64
import hashlib
import ssl


def spki_sha256_b64(der_cert: bytes) -> str:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        cert = x509.load_der_x509_certificate(der_cert)
        spki = cert.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
    except Exception:
        spki = der_cert  # degraded: full cert hash — document in evidence
    return base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")


def peer_spki_sha256(sock: ssl.SSLSocket) -> str | None:
    try:
        der = sock.getpeercert(binary_form=True)
    except Exception:
        return None
    if not isinstance(der, bytes) or not der:
        return None
    return spki_sha256_b64(der)


def verify_spki_pin(
    sock: ssl.SSLSocket, allowed_pins: frozenset[str]
) -> tuple[bool, str | None]:
    observed = peer_spki_sha256(sock)
    if not allowed_pins:
        return True, observed
    if observed is None:
        return False, None
    allowed = {p.strip() for p in allowed_pins}
    if observed in allowed or observed.rstrip("=") in {p.rstrip("=") for p in allowed}:
        return True, observed
    return False, observed