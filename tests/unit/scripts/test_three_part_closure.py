"""Tests for the closure notice template structure.

Verifies that docs/downstream-responses/_template-closure-notice.md
contains all required sections as defined by Rule 15.
"""
import pathlib

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent.parent
TEMPLATE_PATH = REPO_ROOT / "docs" / "downstream-responses" / "_template-closure-notice.md"


def _template_content() -> str:
    assert TEMPLATE_PATH.exists(), f"Template not found: {TEMPLATE_PATH}"
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_template_exists():
    """The template file must exist at the expected path."""
    assert TEMPLATE_PATH.exists(), f"Missing template: {TEMPLATE_PATH}"


def test_template_has_functional_head_placeholder():
    """Template must contain a Functional HEAD placeholder."""
    content = _template_content()
    assert "Functional HEAD:" in content, "Template missing 'Functional HEAD:' line"


def test_template_has_notice_head_placeholder():
    """Template must contain a Notice HEAD placeholder."""
    content = _template_content()
    assert "Notice HEAD:" in content, "Template missing 'Notice HEAD:' line"


def test_template_has_manifest_placeholder():
    """Template must contain a Manifest placeholder."""
    content = _template_content()
    assert "Manifest:" in content, "Template missing 'Manifest:' line"


def test_template_has_three_tier_scorecard():
    """Template must contain all three scorecard row labels."""
    content = _template_content()
    assert "raw_implementation_maturity" in content, "Missing 'raw_implementation_maturity' row"
    assert "current_verified_readiness" in content, "Missing 'current_verified_readiness' row"
    assert "conditional_readiness_after_blockers" in content, (
        "Missing 'conditional_readiness_after_blockers' row"
    )


def test_template_has_level_column_in_defect_table():
    """Template defect table must include a Level column."""
    content = _template_content()
    lines = content.splitlines()
    header_lines = [ln for ln in lines if "| Defect" in ln and "Level" in ln]
    assert header_lines, "No defect table header row containing both 'Defect' and 'Level'"


def test_template_has_status_column_in_defect_table():
    """Template defect table must include a Status column."""
    content = _template_content()
    lines = content.splitlines()
    header_lines = [ln for ln in lines if "| Defect" in ln and "Status" in ln]
    assert header_lines, "No defect table header row containing both 'Defect' and 'Status'"


def test_template_warning_comment_present():
    """Template must include the TEMPLATE warning comment."""
    content = _template_content()
    assert "TEMPLATE" in content, "Template missing TEMPLATE warning comment"
    assert "placeholder" in content.lower(), "Template warning must mention 'placeholder'"


def test_template_status_is_draft():
    """Template must declare Status: draft."""
    content = _template_content()
    assert "Status:" in content and "draft" in content, (
        "Template must contain 'Status: draft' to be exempt from HEAD alignment checks"
    )


def test_template_does_not_contain_real_sha():
    """Template placeholders must not contain a real 40-char hex SHA."""
    import re
    content = _template_content()
    real_sha_pattern = re.compile(r"\b[0-9a-f]{40}\b")
    matches = real_sha_pattern.findall(content)
    assert not matches, f"Template contains what looks like a real SHA: {matches}"
