"""W22-A11: Verify that Status: RELEASED docs face stricter validation (reversal of W16 exemption).

The W16 commit f0b35a2 weakened validation by adding 'released' to the exempt pattern in two
places inside check_doc_consistency.py:
  - check_notice_head_matches_repo: returns [] early for RELEASED docs (no HEAD check)
  - check_notice_head_alignment: skips RELEASED docs in the wave notice loop

W22-A11 reverses this: RELEASED must NOT be in the exempt/skip pattern.
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parents[2] / "scripts"
GATE_FILE = SCRIPTS_DIR / "check_doc_consistency.py"


def test_gate_file_exists():
    """Sanity check: the gate script must exist."""
    assert GATE_FILE.exists(), "check_doc_consistency.py must exist"


def test_released_not_in_check_notice_head_matches_repo_exempt_pattern():
    """After W22-A11: 'released' must not be in the exempt regex in check_notice_head_matches_repo.

    Before the fix (W16), line ~201 read:
        if re.search(r"Status:.*(?:draft|superseded|released)", src, re.IGNORECASE):
            return []  # exits early — no HEAD check for RELEASED docs

    After the fix, 'released' is removed from that pattern so RELEASED docs
    are NOT exempt from HEAD alignment validation.
    """
    src = GATE_FILE.read_text(encoding="utf-8")

    # Find the check_notice_head_matches_repo function body
    func_start = src.find("def check_notice_head_matches_repo(")
    func_end = src.find("\ndef ", func_start + 1)
    if func_end == -1:
        func_end = len(src)
    func_body = src[func_start:func_end]

    # The pattern `(?:draft|superseded|released)` or `draft.*released` or similar must NOT appear
    released_in_exempt = re.search(
        r"Status.*(?:draft|superseded).*released|Status.*released",
        func_body,
    )
    ctx = (
        func_body[max(0, released_in_exempt.start() - 50) : released_in_exempt.end() + 50]
        if released_in_exempt
        else ""
    )
    assert released_in_exempt is None, (
        "check_notice_head_matches_repo still exempts 'released' from HEAD checks.\n"
        "W22-A11: RELEASED must face stricter validation, not be exempted.\n"
        f"Found pattern near: {ctx!r}"
    )


def test_released_not_in_check_notice_head_alignment_exempt_pattern():
    """After W22-A11: 'released' must not be in the exempt regex in check_notice_head_alignment.

    Before the fix (W16), the wave-notice loop read:
        _exempt_pattern = re.compile(r"Status:.*(?:draft|superseded|released)", re.IGNORECASE)
        if any(_exempt_pattern.search(line) for line in lines):
            continue  # draft/superseded/released notices are exempt from HEAD alignment

    After the fix, 'released' is removed so RELEASED wave notices are checked, not skipped.
    """
    src = GATE_FILE.read_text(encoding="utf-8")

    # Find the check_notice_head_alignment function body
    func_start = src.find("def check_notice_head_alignment(")
    func_end = src.find("\ndef ", func_start + 1)
    if func_end == -1:
        func_end = len(src)
    func_body = src[func_start:func_end]

    # Check that 'released' does not appear in an exempt pattern inside this function
    released_in_exempt = re.search(
        r"Status.*(?:draft|superseded).*released|Status.*released",
        func_body,
    )
    ctx = (
        func_body[max(0, released_in_exempt.start() - 50) : released_in_exempt.end() + 50]
        if released_in_exempt
        else ""
    )
    assert released_in_exempt is None, (
        "check_notice_head_alignment still exempts 'released' from HEAD alignment checks.\n"
        "W22-A11: RELEASED wave notices must be validated, not skipped.\n"
        f"Found pattern near: {ctx!r}"
    )


def test_draft_superseded_still_exempt():
    """draft and superseded must remain exempt — only 'released' is being un-exempted."""
    src = GATE_FILE.read_text(encoding="utf-8")

    # draft and superseded should still appear in the exempt patterns
    assert re.search(r"Status.*draft", src), "draft must remain in exempt pattern"
    assert re.search(r"Status.*superseded", src), "superseded must remain in exempt pattern"


def test_no_released_in_any_exempt_pattern():
    """After W22-A11: 'released' must not appear in any Status-based exempt pattern.

    This is a belt-and-suspenders check across the full file: any regex that matches
    a 'Status:...' line must NOT include 'released' as an exempt value.
    """
    src = GATE_FILE.read_text(encoding="utf-8")

    # Find all Status-matching regex patterns and verify none include 'released'
    # Patterns look like: r"Status:.*(?:draft|superseded|released)"
    status_patterns = re.findall(
        r'Status[^"\']*(?:draft|superseded)[^"\']*',
        src,
    )
    for pat in status_patterns:
        assert "released" not in pat.lower(), (
            f"Found a Status-exempt pattern that includes 'released': {pat!r}\n"
            "W22-A11 requires 'released' to NOT be in any exempt pattern."
        )
