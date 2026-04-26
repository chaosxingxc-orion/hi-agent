"""Tests for check_notice_head_alignment() in scripts/check_doc_consistency.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Ensure scripts/ is importable.
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from check_doc_consistency import check_notice_head_alignment

_CURRENT_HEAD = "abcdef1234567890abcdef1234567890abcdef12"
_STALE_HEAD = "deadbeef00000000deadbeef00000000deadbeef"


def _patch_git_head(head: str):
    """Patch _git_head to return a fixed SHA."""
    return patch("check_doc_consistency._git_head", return_value=head)


def _write_notice(tmp_path: Path, name: str, content: str) -> Path:
    notice_dir = tmp_path / "downstream-responses"
    notice_dir.mkdir(parents=True, exist_ok=True)
    p = notice_dir / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Helper to patch DOCS inside the module
# ---------------------------------------------------------------------------


def _patch_docs(tmp_path: Path):
    """Redirect the DOCS path used by check_notice_head_alignment to tmp_path."""
    return patch("check_doc_consistency.DOCS", tmp_path)


# ---------------------------------------------------------------------------
# 1. Notice with current HEAD in Functional HEAD + Notice HEAD → PASS
# ---------------------------------------------------------------------------


def test_current_head_in_both_fields_passes(tmp_path: Path) -> None:
    """A notice file declaring the current HEAD in both HEAD fields must pass."""
    _write_notice(
        tmp_path,
        "2026-04-26-wave10-delivery-notice.md",
        f"# Wave 10 Delivery Notice\n"
        f"Functional HEAD: {_CURRENT_HEAD}\n"
        f"Notice HEAD: {_CURRENT_HEAD}\n",
    )

    with _patch_git_head(_CURRENT_HEAD), _patch_docs(tmp_path):
        errors = check_notice_head_alignment()

    assert errors == []


# ---------------------------------------------------------------------------
# 2. Notice with stale SHA in HEAD fields → emits STALE-NOTICE-HEAD
# ---------------------------------------------------------------------------


def test_stale_head_emits_error(tmp_path: Path) -> None:
    """A non-draft notice with a stale SHA must emit STALE-NOTICE-HEAD."""
    _write_notice(
        tmp_path,
        "2026-04-26-wave10-delivery-notice.md",
        f"# Wave 10 Delivery Notice\n"
        f"Functional HEAD: {_STALE_HEAD}\n"
        f"Notice HEAD: {_STALE_HEAD}\n",
    )

    with _patch_git_head(_CURRENT_HEAD), _patch_docs(tmp_path):
        errors = check_notice_head_alignment()

    assert any("STALE-NOTICE-HEAD" in e for e in errors)
    assert len([e for e in errors if "STALE-NOTICE-HEAD" in e]) >= 1


# ---------------------------------------------------------------------------
# 3. Notice with 'Status: draft' → always PASS (even with stale SHA)
# ---------------------------------------------------------------------------


def test_draft_status_exempts_stale_sha(tmp_path: Path) -> None:
    """A notice file with 'Status: draft' must pass regardless of SHA staleness."""
    _write_notice(
        tmp_path,
        "2026-04-26-wave10-delivery-notice.md",
        f"# Wave 10 Delivery Notice\n"
        f"Status: draft\n"
        f"Functional HEAD: {_STALE_HEAD}\n"
        f"Notice HEAD: {_STALE_HEAD}\n",
    )

    with _patch_git_head(_CURRENT_HEAD), _patch_docs(tmp_path):
        errors = check_notice_head_alignment()

    assert errors == []


# ---------------------------------------------------------------------------
# 4. Notice with legacy HEAD SHA format (bold markdown) → stale → emits error
# ---------------------------------------------------------------------------


def test_legacy_head_sha_field_stale_emits_error(tmp_path: Path) -> None:
    """A notice using the legacy **HEAD SHA:** field with a stale SHA must be flagged."""
    _write_notice(
        tmp_path,
        "2026-04-26-wave10-delivery-notice.md",
        f"# Wave 10 Delivery Notice\n"
        f"**HEAD SHA:** {_STALE_HEAD}\n",
    )

    with _patch_git_head(_CURRENT_HEAD), _patch_docs(tmp_path):
        errors = check_notice_head_alignment()

    assert any("STALE-NOTICE-HEAD" in e for e in errors)


# ---------------------------------------------------------------------------
# 5. Notice with legacy HEAD SHA matching current HEAD → PASS
# ---------------------------------------------------------------------------


def test_legacy_head_sha_field_current_passes(tmp_path: Path) -> None:
    """A notice using the legacy **HEAD SHA:** field with the current SHA must pass."""
    _write_notice(
        tmp_path,
        "2026-04-26-wave10-delivery-notice.md",
        f"# Wave 10 Delivery Notice\n"
        f"**HEAD SHA:** {_CURRENT_HEAD}\n",
    )

    with _patch_git_head(_CURRENT_HEAD), _patch_docs(tmp_path):
        errors = check_notice_head_alignment()

    assert errors == []


# ---------------------------------------------------------------------------
# 6. Non-wave notice file → ignored
# ---------------------------------------------------------------------------


def test_non_wave_notice_is_ignored(tmp_path: Path) -> None:
    """Files not matching '2026-*-wave*-notice.md' must be ignored."""
    _write_notice(
        tmp_path,
        "2026-04-25-h2-delivery-notice.md",
        f"**HEAD SHA:** {_STALE_HEAD}\n",
    )

    with _patch_git_head(_CURRENT_HEAD), _patch_docs(tmp_path):
        errors = check_notice_head_alignment()

    assert errors == []
