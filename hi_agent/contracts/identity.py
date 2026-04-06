"""Deterministic identity contracts."""

from __future__ import annotations

import base64
import hashlib


def deterministic_id(*parts: str) -> str:
    """Build deterministic short ID from ordered string parts.

    Args:
      *parts: Ordered string components that uniquely define identity.

    Returns:
      URL-safe base64-encoded ID derived from first 16 bytes of SHA-256.
    """
    raw = "/".join(parts).encode("utf-8")
    digest = hashlib.sha256(raw).digest()[:16]
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

