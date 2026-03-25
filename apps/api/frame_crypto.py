"""Ed25519 signing for Frame records (FRAME_PRIVATE_KEY; honors FRAME_KEY_FORMAT like Node scripts)."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _load_private_key() -> Ed25519PrivateKey:
    raw = os.environ.get("FRAME_PRIVATE_KEY", "").strip()
    if not raw:
        raise RuntimeError("FRAME_PRIVATE_KEY not set")
    fmt = (os.environ.get("FRAME_KEY_FORMAT") or "pem").strip().lower()
    if fmt == "base64":
        blob = base64.b64decode(raw.strip())
        try:
            pem_text = blob.decode("utf-8")
        except UnicodeDecodeError:
            pem_text = ""
        if "BEGIN" in pem_text and "PRIVATE" in pem_text:
            pem = pem_text.replace("\\n", "\n")
            key = serialization.load_pem_private_key(pem.strip().encode(), password=None)
        else:
            key = serialization.load_der_private_key(blob, password=None)
    else:
        pem = raw.replace("\\n", "\n").strip("\"'")
        key = serialization.load_pem_private_key(pem.strip().encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("FRAME_PRIVATE_KEY must be Ed25519 PEM")
    return key


def frame_content_hash(claim: str, claimant_name: str, timestamp: str) -> str:
    payload = f"{claim}{claimant_name}{timestamp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sign_frame_digest_hex(digest_hex: str) -> str:
    """Sign SHA-256 hex string (as utf-8 bytes) for stable verification."""
    key = _load_private_key()
    sig = key.sign(digest_hex.encode("utf-8"))
    return base64.b64encode(sig).decode("ascii")
