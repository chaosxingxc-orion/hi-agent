"""Tests for check_doc_consistency._check_closure_notice_levels (Check 11)."""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent.parent / "scripts"))


def _write_notice(tmp_dir: pathlib.Path, name: str, content: str) -> pathlib.Path:
    """Write a notice file inside a docs/downstream-responses/ subdirectory."""
    responses_dir = tmp_dir / "downstream-responses"
    responses_dir.mkdir(parents=True, exist_ok=True)
    p = responses_dir / name
    p.write_text(content, encoding="utf-8")
    return p


def test_valid_notice_no_violations():
    """A notice with a valid Level column and valid enum values produces no violations."""
    from check_doc_consistency import _check_closure_notice_levels

    content = """\
# Wave 12 Closure Notice

| Defect | Fix | Gate | Process | Level | Status |
|---|---|---|---|---|---|
| DF-55 | abc1234 | test_foo asserts X | Rule 15 | verified_at_release_head | CLOSED |
| DF-56 | def5678 | test_baz asserts Y | CI gate | wired_into_default_path | IN PROGRESS |
"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        _write_notice(tmp_path, "2026-04-27-wave12-notice.md", content)
        violations = _check_closure_notice_levels(tmp_path)
    assert violations == [], f"Expected no violations, got: {violations}"


def test_invalid_level_value_produces_violation():
    """A notice with an invalid level string in the Level column yields a violation."""
    from check_doc_consistency import _check_closure_notice_levels

    content = """\
# Wave 12 Closure Notice

| Defect | Code Fix | Gate Evidence | Process Change | Level | Status |
|---|---|---|---|---|---|
| DF-57 | commit abc | test_x::test_y asserts Z | Rule 15 | totally_made_up_level | CLOSED |
"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        _write_notice(tmp_path, "2026-04-27-wave12-notice.md", content)
        violations = _check_closure_notice_levels(tmp_path)
    assert len(violations) == 1, f"Expected 1 violation, got: {violations}"
    assert "totally_made_up_level" in violations[0]


def test_notice_without_level_column_is_skipped():
    """A notice table that has no Level column must not produce any violations."""
    from check_doc_consistency import _check_closure_notice_levels

    content = """\
# Wave 12 Closure Notice

| Defect | Code Fix | Status |
|---|---|---|
| DF-58 | commit abc | CLOSED |
"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        _write_notice(tmp_path, "2026-04-27-wave12-notice.md", content)
        violations = _check_closure_notice_levels(tmp_path)
    assert violations == [], (
        f"Expected no violations for table without Level column, got: {violations}"
    )


def test_empty_downstream_responses_dir_returns_empty():
    """If docs/downstream-responses/ exists but has no notice files, return empty list."""
    from check_doc_consistency import _check_closure_notice_levels

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        responses_dir = tmp_path / "downstream-responses"
        responses_dir.mkdir()
        violations = _check_closure_notice_levels(tmp_path)
    assert violations == []


def test_missing_downstream_responses_dir_returns_empty():
    """If docs/downstream-responses/ does not exist at all, return empty list gracefully."""
    from check_doc_consistency import _check_closure_notice_levels

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        violations = _check_closure_notice_levels(tmp_path)
    assert violations == []


def test_multiple_invalid_levels_produce_multiple_violations():
    """Two rows with invalid levels produce two violations."""
    from check_doc_consistency import _check_closure_notice_levels

    content = """\
# Wave 12 Closure Notice

| Defect | Level | Status |
|---|---|---|
| DF-60 | bad_level_one | CLOSED |
| DF-61 | bad_level_two | CLOSED |
"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        _write_notice(tmp_path, "2026-04-27-wave12-notice.md", content)
        violations = _check_closure_notice_levels(tmp_path)
    assert len(violations) == 2, f"Expected 2 violations, got: {violations}"


def test_all_valid_levels_accepted():
    """All five canonical levels plus in_progress and deferred are accepted."""
    from check_doc_consistency import _check_closure_notice_levels

    rows = "\n".join(
        f"| DF-{70 + i} | commit abc | test::fn asserts x | Rule 15 | {level} | IN PROGRESS |"
        for i, level in enumerate([
            "component_exists",
            "wired_into_default_path",
            "covered_by_default_path_e2e",
            "verified_at_release_head",
            "operationally_observable",
            "in_progress",
            "deferred",
        ])
    )
    content = f"""\
# Wave 12 Closure Notice

| Defect | Code Fix | Gate Evidence | Process Change | Level | Status |
|---|---|---|---|---|---|
{rows}
"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        _write_notice(tmp_path, "2026-04-27-wave12-notice.md", content)
        violations = _check_closure_notice_levels(tmp_path)
    assert violations == [], f"All valid levels should pass, got: {violations}"
