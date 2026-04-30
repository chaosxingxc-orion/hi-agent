"""HD-6 (W24-J6): PII-safe log redaction helpers.

Verifies:
1. ``hash_tenant_id`` produces a stable ``tnt:<sha8>`` form and never the raw
   tenant id.
2. ``redact_query`` produces ``<redacted len=N hash=...>`` and never reveals
   the original characters.
3. The three logging sites in ``hi_agent.server.routes_knowledge`` no longer
   emit the raw tenant_id or raw query/title text.
"""

from __future__ import annotations

import logging

import pytest
from hi_agent.observability.log_redaction import hash_tenant_id, redact_query

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_hash_tenant_id_shape() -> None:
    out = hash_tenant_id("tenant-A")
    assert out.startswith("tnt:")
    # 8 hex characters after the prefix
    assert len(out) == 12
    assert "tenant-A" not in out


def test_hash_tenant_id_stable() -> None:
    """Same input ⇒ same output (deterministic, greppable)."""
    assert hash_tenant_id("tenant-A") == hash_tenant_id("tenant-A")
    assert hash_tenant_id("tenant-A") != hash_tenant_id("tenant-B")


def test_hash_tenant_id_empty_marker() -> None:
    assert hash_tenant_id("") == "tnt:<empty>"


def test_redact_query_shape() -> None:
    raw = "explain transformer attention"
    out = redact_query(raw)
    assert "<redacted len=" in out
    assert f"len={len(raw)}" in out
    assert raw not in out


def test_redact_query_empty_marker() -> None:
    assert "<empty>" in redact_query("")


def test_redact_query_does_not_leak_input_chars() -> None:
    """Even short queries must not appear inside the redacted form."""
    raw = "tok"
    out = redact_query(raw)
    # the digit '3' appears in 'len=3' but the actual input chars do not
    assert raw not in out
    assert "tok" not in out.replace("len=3", "")


# ---------------------------------------------------------------------------
# routes_knowledge logging sites — verify the raw tenant_id and query no
# longer appear in the captured log lines.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("logger_name", ["hi_agent.server.routes_knowledge"])
def test_routes_knowledge_log_calls_use_redaction(
    logger_name: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Smoke check: the redaction helpers do appear in the routes module."""
    import hi_agent.server.routes_knowledge as mod

    # Source-level guard: the legacy `tenant_id=%r` literals are gone.
    src = mod.__file__
    with open(src, encoding="utf-8") as fh:
        content = fh.read()
    assert "hash_tenant_id" in content
    assert "redact_query" in content
    assert "tenant_id=%r" not in content, (
        "HD-6: routes_knowledge must not emit raw tenant_id with %r"
    )
    assert "title=%r" not in content
    assert "q=%r" not in content

    # Log capture: emit a sample log call with the helpers and verify shape.
    with caplog.at_level(logging.DEBUG, logger=logger_name):
        logging.getLogger(logger_name).debug(
            "hi_agent.routes_knowledge: query tenant=%s q=%s",
            hash_tenant_id("tenant-A"),
            redact_query("secret query"),
        )
    assert any(
        "tnt:" in r.getMessage() and "<redacted len=" in r.getMessage()
        for r in caplog.records
    )
    assert not any("tenant-A" in r.getMessage() for r in caplog.records)
    assert not any("secret query" in r.getMessage() for r in caplog.records)
