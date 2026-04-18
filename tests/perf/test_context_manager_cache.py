"""Tests for the section-level cache added to ContextManager (TASK-PERF-3c)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hi_agent.context.manager import ContextManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(**kwargs) -> ContextManager:
    """Return a fresh ContextManager with no external dependencies."""
    return ContextManager(**kwargs)


# ---------------------------------------------------------------------------
# Test 1: Cache is initialised on construction
# ---------------------------------------------------------------------------


def test_cache_initialized_on_construction():
    """_section_cache and _section_dirty must exist on a fresh ContextManager."""
    mgr = _make_manager()
    assert hasattr(mgr, "_section_cache"), "_section_cache missing"
    assert hasattr(mgr, "_section_dirty"), "_section_dirty missing"
    assert isinstance(mgr._section_cache, dict)
    assert isinstance(mgr._section_dirty, dict)
    # Dynamic sections must be present and dirty on startup
    for name in ("memory", "history", "reflection"):
        assert name in mgr._section_dirty, f"{name} not in _section_dirty"
        assert mgr._section_dirty[name] is True, f"{name} should start dirty"


# ---------------------------------------------------------------------------
# Test 2: Stable section cache hit — same system prompt
# ---------------------------------------------------------------------------


def test_stable_section_cache_hit():
    """Second call with the same system prompt must return a cached section
    and increment the metrics counter when a metrics sink is present."""
    mgr = _make_manager()

    # Attach a mock metrics sink
    metrics = MagicMock()
    mgr._metrics = metrics

    prompt = "You are a helpful assistant."

    # First call — cache miss, section is built and stored
    section1 = mgr._assemble_system(prompt)
    metrics.increment.assert_not_called()  # no hit on first call

    # Second call — cache hit expected
    section2 = mgr._assemble_system(prompt)
    metrics.increment.assert_called_once_with(
        "context_cache_hit", {"section": "system"}
    )

    # Both calls must return equal content
    assert section1.content == section2.content
    assert section1.tokens == section2.tokens


# ---------------------------------------------------------------------------
# Test 3: Stable sections invalidate on content change
# ---------------------------------------------------------------------------


def test_stable_sections_invalidate_on_change():
    """Changing the system prompt content must produce a cache miss and a
    new fingerprint entry in _section_cache."""
    mgr = _make_manager()

    prompt_a = "System prompt A"
    prompt_b = "System prompt B (different)"

    section_a = mgr._assemble_system(prompt_a)
    fp_a = mgr._section_cache["system"][0]

    section_b = mgr._assemble_system(prompt_b)
    fp_b = mgr._section_cache["system"][0]

    assert section_a.content != section_b.content
    assert fp_a != fp_b, "Fingerprint must change when content changes"


# ---------------------------------------------------------------------------
# Test 4: history dirty flag is True after _compact_history
# ---------------------------------------------------------------------------


def test_history_dirty_after_compact():
    """After _compact_history() runs, _section_dirty['history'] must be True."""
    # Provide a minimal compressor stub
    compressor = MagicMock()
    compressor.compress_text = MagicMock(return_value="summary text")

    mgr = _make_manager(compressor=compressor)
    mgr.add_history_entry("user", "hello")
    mgr.add_history_entry("assistant", "hi there")

    # Build history to clear the dirty flag first
    _ = mgr._assemble_history()
    assert mgr._section_dirty["history"] is False, "dirty flag should be False after build"

    # Now compact — this should re-set the dirty flag
    from hi_agent.context.manager import ContextSection
    history_section = ContextSection(
        name="history",
        content="[user] hello\n[assistant] hi there",
        tokens=10,
        budget=1000,
        source="session_history",
    )
    mgr._compact_history(history_section, target_tokens=500)

    assert mgr._section_dirty["history"] is True, (
        "_compact_history must mark history dirty so the next assemble rebuilds it"
    )


# ---------------------------------------------------------------------------
# Test 5: Dynamic sections rebuild after dirty flag is set
# ---------------------------------------------------------------------------


def test_dynamic_section_rebuilds_when_dirty():
    """add_history_entry must mark the history section dirty so subsequent
    calls to _assemble_history produce a fresh section, not a stale cache."""
    mgr = _make_manager()

    # First build — populates cache
    s1 = mgr._assemble_history()
    assert mgr._section_dirty["history"] is False

    # Add a new entry — marks dirty
    mgr.add_history_entry("user", "new message")
    assert mgr._section_dirty["history"] is True

    # Next build — must include new entry
    s2 = mgr._assemble_history()
    assert "new message" in s2.content
    assert mgr._section_dirty["history"] is False


# ---------------------------------------------------------------------------
# Test 6: set_reflection_context marks reflection dirty
# ---------------------------------------------------------------------------


def test_reflection_dirty_after_set():
    """set_reflection_context must mark reflection dirty so next assemble
    rebuilds the section with the new content."""
    mgr = _make_manager()

    # First assemble — clears dirty
    _ = mgr._assemble_reflection()
    assert mgr._section_dirty["reflection"] is False

    mgr.set_reflection_context("Retry: attempt 2 failed because of X")
    assert mgr._section_dirty["reflection"] is True

    section = mgr._assemble_reflection()
    assert "Retry" in section.content
    assert mgr._section_dirty["reflection"] is False
