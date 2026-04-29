"""Posture-matrix tests for server module callsites (Rule 11).

Covers:
  hi_agent/server/run_queue.py      — _resolve_db_path
  hi_agent/management/gate_store.py — _warn_unscoped_gate_read

Test function names are test_<source_function_name> so check_posture_coverage.py
matches them to the corresponding callsite function names.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# run_queue._resolve_db_path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,expect_memory", [
    ("dev", True),
    ("research", False),
    ("prod", False),
])
def test__resolve_db_path(monkeypatch, posture_name, expect_memory, tmp_path):
    """Posture-matrix test for _resolve_db_path.

    dev: returns ':memory:'.
    research/prod: returns durable file path (requires HI_AGENT_DATA_DIR).
    Explicit path always returned unchanged.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.server.run_queue import _resolve_db_path

    if expect_memory:
        result = _resolve_db_path(None)
        assert result == ":memory:"
    else:
        monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
        result = _resolve_db_path(None)
        assert result != ":memory:"
        assert "run_queue.sqlite" in result

    # Explicit path always passes through
    explicit = str(tmp_path / "explicit.sqlite")
    assert _resolve_db_path(explicit) == explicit


# ---------------------------------------------------------------------------
# gate_store._warn_unscoped_gate_read
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,should_raise", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__warn_unscoped_gate_read(monkeypatch, posture_name, should_raise):
    """Posture-matrix test for _warn_unscoped_gate_read.

    dev: emits WARNING, does not raise.
    research/prod: raises ValueError for missing tenant_id.
    internal_unscoped=True always bypasses checks.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.management.gate_store import _warn_unscoped_gate_read

    # internal_unscoped=True must never raise in any posture
    _warn_unscoped_gate_read("apply_timeouts", gate_ref="g-1", internal_unscoped=True)

    if should_raise:
        with pytest.raises(ValueError, match="tenant_id"):
            _warn_unscoped_gate_read("resolve", gate_ref="g-1")
    else:
        _warn_unscoped_gate_read("resolve", gate_ref="g-1")  # warns, does not raise
