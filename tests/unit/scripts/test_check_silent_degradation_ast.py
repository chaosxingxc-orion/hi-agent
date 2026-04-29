"""Tests for AST-based silent-degradation detection in check_silent_degradation.py.

Covers the six core detection cases documented in the spec, plus edge cases
for the new multi-line detection that was invisible to the old line-based checker.
"""
from __future__ import annotations

import pathlib
import sys
import textwrap

# Make the detection function importable
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent.parent / "scripts"))


def _violations(src: str) -> list[dict]:
    """Parse src as a temp file and return violations."""
    import tempfile
    from pathlib import Path

    from check_silent_degradation import check_file

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", delete=False) as f:
        f.write(src)
        tmp = Path(f.name)
    try:
        return check_file(tmp)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Case 1: Single-line except: pass — detected
# ---------------------------------------------------------------------------
def test_single_line_bare_except_pass_detected():
    """Single-line bare 'except: pass' must be detected."""
    src = textwrap.dedent("""\
        def foo():
            try:
                x = 1
            except:
                pass
    """)
    vs = _violations(src)
    assert len(vs) == 1
    assert vs[0]["status"] == "fail"
    assert "bare except" in vs[0]["exc_type"]


# ---------------------------------------------------------------------------
# Case 2: Multi-line except Exception:\n    pass — detected (THIS was the gap)
# ---------------------------------------------------------------------------
def test_multiline_except_exception_pass_detected():
    """Multi-line 'except Exception: <newline> pass' must be detected.

    This was invisible to the old single-line regex checker.
    """
    src = textwrap.dedent("""\
        def bar():
            try:
                do_something()
            except Exception:
                pass
    """)
    vs = _violations(src)
    assert len(vs) == 1, f"Expected 1 violation, got {len(vs)}: {vs}"
    assert vs[0]["status"] == "fail"
    assert vs[0]["exc_type"] == "Exception"


# ---------------------------------------------------------------------------
# Case 3: except SomeError:\n    return None — detected
# ---------------------------------------------------------------------------
def test_except_some_error_return_none_detected():
    """'except SomeError: return None' must be detected as silent swallow."""
    src = textwrap.dedent("""\
        def baz():
            try:
                call()
            except KeyError:
                return None
    """)
    vs = _violations(src)
    assert len(vs) == 1, f"Expected 1, got: {vs}"
    assert vs[0]["status"] == "fail"
    assert vs[0]["exc_type"] == "KeyError"


# ---------------------------------------------------------------------------
# Case 4: except KeyError:\n    logger.warning(...) — NOT detected (has real body)
# ---------------------------------------------------------------------------
def test_except_with_logging_not_detected():
    """An except block that logs must NOT be flagged as silent swallow."""
    src = textwrap.dedent("""\
        import logging
        _logger = logging.getLogger(__name__)

        def qux():
            try:
                do_something()
            except KeyError as exc:
                _logger.warning("key missing: %s", exc)
    """)
    vs = _violations(src)
    assert vs == [], f"Should not detect logging handler, got: {vs}"


# ---------------------------------------------------------------------------
# Case 5: except Exception: # rule7-exempt: issue=W19-001 — NOT detected (exempted)
# ---------------------------------------------------------------------------
def test_rule7_exempt_annotation_skips_detection():
    """A fully-exempt 'rule7-exempt:' annotation (no expiry_wave) skips detection."""
    src = textwrap.dedent("""\
        def guarded():
            try:
                emit_metric()
            except Exception:  # rule7-exempt: issue=W19-001
                pass
    """)
    vs = _violations(src)
    assert vs == [], f"rule7-exempt should be skipped entirely, got: {vs}"


# ---------------------------------------------------------------------------
# Case 6: except Exception:\n    raise — NOT detected (re-raises)
# ---------------------------------------------------------------------------
def test_except_reraise_not_detected():
    """An except block that re-raises must NOT be flagged."""
    src = textwrap.dedent("""\
        def strict():
            try:
                risky()
            except Exception:
                raise
    """)
    vs = _violations(src)
    assert vs == [], f"re-raise should not be flagged, got: {vs}"


# ---------------------------------------------------------------------------
# Extra: expiry_wave annotation produces 'deferred' status
# ---------------------------------------------------------------------------
def test_expiry_wave_annotation_produces_deferred():
    """'rule7-exempt: expiry_wave=...' must produce status=deferred, not fail."""
    src = textwrap.dedent("""\
        def tracked_debt():
            try:
                something()
            except Exception:  # rule7-exempt: expiry_wave="Wave 21"
                pass
    """)
    vs = _violations(src)
    assert len(vs) == 1, f"Expected 1 deferred violation, got: {vs}"
    assert vs[0]["status"] == "deferred"


# ---------------------------------------------------------------------------
# Extra: except block with raise-from not flagged
# ---------------------------------------------------------------------------
def test_except_raise_from_not_detected():
    """'except X: raise RuntimeError(...) from exc' must not be flagged."""
    src = textwrap.dedent("""\
        def wrap():
            try:
                call()
            except ValueError as exc:
                raise RuntimeError("wrapped") from exc
    """)
    vs = _violations(src)
    assert vs == [], f"raise-from should not be flagged, got: {vs}"


# ---------------------------------------------------------------------------
# Extra: except with Ellipsis body — detected
# ---------------------------------------------------------------------------
def test_except_ellipsis_body_detected():
    """An except block containing only '...' (Ellipsis) is a silent swallow."""
    src = textwrap.dedent("""\
        def stub():
            try:
                action()
            except TypeError:
                ...
    """)
    vs = _violations(src)
    assert len(vs) == 1, f"Ellipsis body should be detected, got: {vs}"
    assert vs[0]["status"] == "fail"


# ---------------------------------------------------------------------------
# Extra: contextlib.suppress(Exception) flagged
# ---------------------------------------------------------------------------
def test_contextlib_suppress_exception_detected():
    """contextlib.suppress(Exception) must be flagged as overly broad suppression."""
    src = textwrap.dedent("""\
        import contextlib

        def broad():
            with contextlib.suppress(Exception):
                risky()
    """)
    vs = _violations(src)
    assert len(vs) == 1, f"suppress(Exception) should be detected, got: {vs}"
    assert vs[0]["pattern"] == "suppress_exception_broad"
