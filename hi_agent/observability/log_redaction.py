"""HD-6 (W24-J6): PII-safe redaction helpers for log lines.

Routes that handle tenant-scoped data must not write tenant identifiers or
free-text user input to logs in clear form — both are PII surfaces under
research/prod posture. These helpers produce stable, hash-anchored stand-ins
so log lines stay greppable for debugging without leaking the underlying
values.

Usage::

    from hi_agent.observability.log_redaction import hash_tenant_id, redact_query
    _logger.debug(
        "knowledge.query tenant=%s q=%s",
        hash_tenant_id(tenant_id),
        redact_query(q),
    )
"""

from __future__ import annotations

import hashlib


def hash_tenant_id(tenant_id: str) -> str:
    """Return a non-reversible 8-char SHA-256 prefix prefixed with ``tnt:``.

    An empty / falsy tenant_id maps to ``tnt:<empty>`` so that the absence
    is itself observable.

    Examples::

        >>> hash_tenant_id("tenant-A")
        'tnt:9c7c93e2'
        >>> hash_tenant_id("")
        'tnt:<empty>'
    """
    if not tenant_id:
        return "tnt:<empty>"
    digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()
    return f"tnt:{digest[:8]}"


def redact_query(q: str, max_chars: int = 20) -> str:
    """Return a redacted, length-capped representation of a free-text query.

    Replaces the raw query text with ``<redacted len=N hash=XXXXXXXX>``
    where ``N`` is the original length and ``XXXXXXXX`` is the first 8
    chars of a SHA-256 hex digest. ``max_chars`` is retained as a parameter
    for backward compatibility but the redacted output never includes any
    of the original characters.

    Examples::

        >>> redact_query("explain transformer attention")
        '<redacted len=29 hash=...>'
        >>> redact_query("")
        '<redacted len=0 hash=<empty>>'
    """
    if not isinstance(q, str):
        q = str(q)
    if not q:
        return "<redacted len=0 hash=<empty>>"
    digest = hashlib.sha256(q.encode("utf-8")).hexdigest()[:8]
    # max_chars is accepted but unused — kept for API stability so callers
    # that pre-tune a length cap do not break when redaction tightens later.
    _ = max_chars
    return f"<redacted len={len(q)} hash={digest}>"
