"""Unit tests for check_doc_consistency script.

The full-script integration test previously asserted returncode == 0.  After
Wave 10.1 Track E, the script now also checks:
  E1a — delivery notice HEAD matches repo HEAD
  E1b — T3 DEFERRED contradicts readiness > 72
  E1c — claimed SHA is reachable in git history

The Wave 10 delivery notice at HEAD intentionally has a stale HEAD claim
(678382e vs actual 5c5b6f4) and a T3-DEFERRED vs readiness contradiction,
so the full-script run correctly returns exit code 1.  The tests below verify
each new check function in isolation against synthetic inputs.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_doc_consistency.py"

# ---------------------------------------------------------------------------
# Smoke: script is importable and individual checks are callable
# ---------------------------------------------------------------------------


def test_check_doc_consistency_script_is_importable():
    """Script must be importable without error."""
    result = subprocess.run(
        [sys.executable, "-c", f"import importlib.util; "
         f"spec = importlib.util.spec_from_file_location('cdc', r'{SCRIPT}'); "
         f"mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Import failed:\n{result.stderr}"


# ---------------------------------------------------------------------------
# E1a — HEAD binding check
# ---------------------------------------------------------------------------


def test_e1a_no_error_when_notice_matches_head(tmp_path):
    """E1a passes when the notice HEAD SHA matches the actual repo HEAD."""
    import sys
    sys.path.insert(0, str(SCRIPT.parent.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("cdc", SCRIPT)
    cdc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdc)

    fake_sha = "abcdef1234567890abcdef1234567890abcdef12"
    notice = tmp_path / "2026-01-01-delivery-notice.md"
    notice.write_text(f"**HEAD SHA:** {fake_sha}\n")

    with patch.object(cdc, "_git_head", return_value=fake_sha):
        errors = cdc.check_notice_head_matches_repo(notice)
    assert errors == []


def test_e1a_error_when_notice_sha_differs(tmp_path):
    """E1a emits FAIL when claimed SHA differs from repo HEAD."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cdc", SCRIPT)
    cdc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdc)

    claimed = "aaaaaaa1234567890abcdef1234567890abcdef1"
    actual = "bbbbbbb1234567890abcdef1234567890abcdef1"
    # Place notice inside repo root so relative_to(ROOT) resolves correctly.
    repo_root = SCRIPT.parent.parent
    notice = repo_root / "docs" / "downstream-responses" / "_test-delivery-notice.md"
    notice.write_text(f"**HEAD SHA:** {claimed}\n")
    try:
        with patch.object(cdc, "_git_head", return_value=actual):
            errors = cdc.check_notice_head_matches_repo(notice)
    finally:
        notice.unlink(missing_ok=True)
    assert len(errors) == 1
    assert claimed in errors[0]
    assert actual in errors[0]


def test_e1a_skipped_when_pre_final_marker_present(tmp_path):
    """E1a passes when notice contains 'notice-pre-final-commit: true'."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cdc", SCRIPT)
    cdc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdc)

    claimed = "aaaaaaa1234567890abcdef1234567890abcdef1"
    actual = "bbbbbbb1234567890abcdef1234567890abcdef1"
    notice = tmp_path / "2026-01-01-delivery-notice.md"
    notice.write_text(f"**HEAD SHA:** {claimed}\nnotice-pre-final-commit: true\n")

    with patch.object(cdc, "_git_head", return_value=actual):
        errors = cdc.check_notice_head_matches_repo(notice)
    assert errors == []


def test_e1a_no_error_when_no_notice(tmp_path):
    """E1a is non-fatal when no delivery notice exists."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cdc", SCRIPT)
    cdc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdc)

    errors = cdc.check_notice_head_matches_repo(None)
    assert errors == []


# ---------------------------------------------------------------------------
# E1b — T3 DEFERRED vs readiness contradiction
# ---------------------------------------------------------------------------


def test_e1b_error_on_t3_deferred_with_high_readiness(tmp_path):
    """E1b detects T3 DEFERRED notice that also claims readiness above 72."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cdc", SCRIPT)
    cdc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdc)

    content = textwrap.dedent("""\
        **T3 evidence:** DEFERRED — gate run required.

        **Scorecard delta (predicted):** 60.5 -> 73-75
    """)
    repo_root = SCRIPT.parent.parent
    notice = repo_root / "docs" / "downstream-responses" / "_test-delivery-notice.md"
    notice.write_text(content)
    try:
        errors = cdc.check_notice_t3_deferred_vs_readiness(notice)
    finally:
        notice.unlink(missing_ok=True)
    assert len(errors) == 1
    assert "readiness improvement" in errors[0]


def test_e1b_no_error_when_t3_not_deferred(tmp_path):
    """E1b passes when T3 evidence is a real SHA (not DEFERRED)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cdc", SCRIPT)
    cdc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdc)

    content = textwrap.dedent("""\
        **T3 evidence:** docs/delivery/2026-01-01-abc1234.json

        **Scorecard delta:** 60 -> 75
    """)
    notice = tmp_path / "2026-01-01-delivery-notice.md"
    notice.write_text(content)
    errors = cdc.check_notice_t3_deferred_vs_readiness(notice)
    assert errors == []


def test_e1b_no_error_when_readiness_below_threshold(tmp_path):
    """E1b passes when T3 is DEFERRED but readiness stays at or below 72."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cdc", SCRIPT)
    cdc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdc)

    content = textwrap.dedent("""\
        **T3 evidence:** DEFERRED

        **Scorecard delta:** 60 -> 72
    """)
    notice = tmp_path / "2026-01-01-delivery-notice.md"
    notice.write_text(content)
    errors = cdc.check_notice_t3_deferred_vs_readiness(notice)
    assert errors == []


# ---------------------------------------------------------------------------
# E1c — SHA reachability
# ---------------------------------------------------------------------------


def test_e1c_error_on_unreachable_sha(tmp_path):
    """E1c detects a claimed SHA that does not appear in git history."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cdc", SCRIPT)
    cdc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdc)

    ghost_sha = "deadbeefdeadbeefdeadbeefdeadbeef00000000"
    repo_root = SCRIPT.parent.parent
    notice = repo_root / "docs" / "downstream-responses" / "_test-delivery-notice.md"
    notice.write_text(f"**HEAD SHA:** {ghost_sha}\n")

    # Patch subprocess to return a log that does NOT contain ghost_sha
    fake_log = "aaaaaaa\nbbbbbbb\nccccccc\n"
    try:
        with patch("subprocess.check_output", return_value=fake_log.encode()):
            errors = cdc.check_notice_sha_reachable(notice)
    finally:
        notice.unlink(missing_ok=True)
    assert len(errors) == 1
    assert ghost_sha in errors[0]
    assert "not reachable" in errors[0]


def test_e1c_no_error_when_sha_reachable(tmp_path):
    """E1c passes when the claimed SHA prefix appears in git log."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cdc", SCRIPT)
    cdc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdc)

    real_sha = "abcdef1234567890abcdef1234567890abcdef12"
    notice = tmp_path / "2026-01-01-delivery-notice.md"
    notice.write_text(f"**HEAD SHA:** {real_sha}\n")

    fake_log = f"{real_sha}\nothers\n"
    with patch("subprocess.check_output", return_value=fake_log.encode()):
        errors = cdc.check_notice_sha_reachable(notice)
    assert errors == []
