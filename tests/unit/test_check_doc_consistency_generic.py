"""check_doc_consistency must accept any well-formed delivery notice format.

It must NOT require 'Validated by:' or any downstream-specific scorecard header.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def test_no_validated_by_requirement_in_check_doc_consistency():
    """The check_doc_consistency script must not reference 'Validated by:'."""
    src = (ROOT / "scripts" / "check_doc_consistency.py").read_text(encoding="utf-8")
    assert "Validated by:" not in src, (
        "check_doc_consistency.py contains 'Validated by:' — this is downstream-specific. "
        "Move it to check_downstream_response_format.py"
    )


def test_no_hardcoded_score_in_check_doc_consistency():
    """check_doc_consistency must not enforce a hardcoded downstream scorecard threshold."""
    src = (ROOT / "scripts" / "check_doc_consistency.py").read_text(encoding="utf-8")
    # The number 76.5 is a downstream scorecard threshold — platform CI must not enforce it
    assert "76.5" not in src, (
        "check_doc_consistency.py contains '76.5' — this is a downstream scorecard threshold. "
        "Move it to check_downstream_response_format.py"
    )


def test_downstream_response_format_script_exists():
    """check_downstream_response_format.py must exist as the optional consumer script."""
    path = ROOT / "scripts" / "check_downstream_response_format.py"
    assert path.exists(), "scripts/check_downstream_response_format.py must exist"
