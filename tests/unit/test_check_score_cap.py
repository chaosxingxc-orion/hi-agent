"""Tests for check_score_cap() in scripts/check_downstream_response_format.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure scripts/ is importable.
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from check_downstream_response_format import check_score_cap

_HEAD = "abcdef1234567890abcdef1234567890abcdef12"


def _write_notice(tmp_path: Path, score: float, validated_by: str = "") -> Path:
    """Write a minimal delivery notice declaring *score*."""
    notice_dir = tmp_path / "downstream-responses"
    notice_dir.mkdir(parents=True, exist_ok=True)
    p = notice_dir / "2026-04-26-wave10-delivery-notice.md"
    validated_line = f"Validated by: {validated_by}\n" if validated_by else ""
    p.write_text(
        f"# Wave 10 Delivery Notice\n"
        f"```\n"
        f"Current verified readiness: {score}\n"
        f"{validated_line}"
        f"```\n",
        encoding="utf-8",
    )
    return p


def _write_delivery_json(delivery_dir: Path, sha7: str) -> Path:
    """Write a minimal rule15 JSON delivery record matching *sha7*."""
    delivery_dir.mkdir(parents=True, exist_ok=True)
    p = delivery_dir / f"2026-04-26-{sha7}-rule15-volces.json"
    p.write_text(json.dumps({"sha": sha7, "passed": True}), encoding="utf-8")
    return p


def _patch_docs(tmp_path: Path):
    return patch("check_downstream_response_format.DOCS", tmp_path)


def _patch_t3(fresh: bool):
    return patch("check_downstream_response_format._t3_is_fresh", return_value=fresh)


def _patch_t3_deferred(deferred: bool):
    return patch("check_downstream_response_format._t3_is_deferred", return_value=deferred)


def _patch_git_head(sha: str):
    return patch("check_downstream_response_format._git_head", return_value=sha)


# ---------------------------------------------------------------------------
# 1. T3 stale + score 78 → SCORE-CAP-VIOLATION
# ---------------------------------------------------------------------------


def test_t3_stale_score_above_cap_emits_violation(tmp_path: Path) -> None:
    """T3 stale (not deferred) + score 70 must emit SCORE-CAP-VIOLATION (cap is 63.0)."""
    _write_notice(tmp_path, score=70.0)

    with _patch_docs(tmp_path), _patch_t3(False), _patch_t3_deferred(False), _patch_git_head(_HEAD):
        errors = check_score_cap()

    assert any("SCORE-CAP-VIOLATION" in e for e in errors)
    assert any("63.0" in e for e in errors)


# ---------------------------------------------------------------------------
# 2. T3 fresh (evidence present) + score 78 → PASS
# ---------------------------------------------------------------------------


def test_t3_fresh_with_evidence_score_78_passes(tmp_path: Path) -> None:
    """T3 fresh + clean-env evidence + score 78 must pass (no cap)."""
    _write_notice(tmp_path, score=78.0, validated_by="scripts/check_downstream_response_format.py")
    delivery_dir = tmp_path / "delivery"
    _write_delivery_json(delivery_dir, _HEAD[:7])

    with _patch_docs(tmp_path), _patch_t3(True), _patch_git_head(_HEAD):
        errors = check_score_cap()

    assert errors == []


# ---------------------------------------------------------------------------
# 3. T3 stale + score 76.0 → PASS (within cap)
# ---------------------------------------------------------------------------


def test_t3_stale_score_within_cap_passes(tmp_path: Path) -> None:
    """T3 stale (not deferred) + score 60.0 must pass (cap is 63.0 per score_caps.yaml)."""
    _write_notice(tmp_path, score=60.0)

    with _patch_docs(tmp_path), _patch_t3(False), _patch_t3_deferred(False), _patch_git_head(_HEAD):
        errors = check_score_cap()

    assert errors == []


# ---------------------------------------------------------------------------
# 4. T3 fresh but no clean-env evidence JSON + score 78.5 → VIOLATION
# ---------------------------------------------------------------------------


def test_t3_fresh_no_evidence_score_above_cap_emits_violation(tmp_path: Path) -> None:
    """T3 fresh, no clean-env evidence, score 85 → SCORE-CAP-VIOLATION (gate_warn cap 80.0)."""
    _write_notice(tmp_path, score=85.0)
    # No delivery JSON created → has_clean_env_evidence = False

    with _patch_docs(tmp_path), _patch_t3(True), _patch_git_head(_HEAD):
        errors = check_score_cap()

    assert any("SCORE-CAP-VIOLATION" in e for e in errors)
    assert any("80.0" in e for e in errors)


# ---------------------------------------------------------------------------
# 5. T3 fresh but no clean-env evidence + score 77.5 → PASS
# ---------------------------------------------------------------------------


def test_t3_fresh_no_evidence_score_within_cap_passes(tmp_path: Path) -> None:
    """T3 fresh but no clean-env evidence + score 77.5 must pass (cap 78.0)."""
    _write_notice(tmp_path, score=77.5, validated_by="scripts/check_downstream_response_format.py")

    with _patch_docs(tmp_path), _patch_t3(True), _patch_git_head(_HEAD):
        errors = check_score_cap()

    assert errors == []


# ---------------------------------------------------------------------------
# 6. No delivery notices → no errors (nothing to check)
# ---------------------------------------------------------------------------


def test_no_delivery_notices_returns_no_errors(tmp_path: Path) -> None:
    """When no delivery-notice files exist, check_score_cap must return no errors."""
    (tmp_path / "downstream-responses").mkdir(parents=True, exist_ok=True)

    with _patch_docs(tmp_path), _patch_t3(False), _patch_git_head(_HEAD):
        errors = check_score_cap()

    assert errors == []
