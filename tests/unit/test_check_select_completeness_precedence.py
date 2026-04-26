"""Tests that check_select_completeness.py catches exec_ctx-wins precedence violations.

Layer 1 — Unit tests for the check_exec_ctx_precedence() helper.
"""
from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_select_completeness.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("_check_sc_prec", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def checker():
    return _load_checker()


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


def test_exec_ctx_wins_pattern_flagged(checker, tmp_path):
    """A file using exec_ctx.field or kwargs.get(...) is reported as a violation."""
    bad = tmp_path / "bad_writer.py"
    bad.write_text(
        textwrap.dedent(
            """\
            def create(self, exec_ctx=None, **kwargs):
                tenant_id = exec_ctx.tenant_id or kwargs.get("tenant_id")
            """
        ),
        encoding="utf-8",
    )
    issues = checker.check_exec_ctx_precedence(tmp_path)
    assert len(issues) >= 1, f"Expected at least one issue, got: {issues}"
    assert any("exec_ctx-wins" in i for i in issues), issues


def test_kwargs_wins_pattern_not_flagged(checker, tmp_path):
    """A file using tenant_id or exec_ctx.tenant_id (kwargs-wins) is not flagged."""
    good = tmp_path / "good_writer.py"
    good.write_text(
        textwrap.dedent(
            """\
            def create(self, exec_ctx=None, tenant_id="", **kwargs):
                tenant_id = tenant_id or (exec_ctx.tenant_id if exec_ctx else "")
            """
        ),
        encoding="utf-8",
    )
    issues = checker.check_exec_ctx_precedence(tmp_path)
    assert issues == [], f"Expected no issues, got: {issues}"


def test_file_without_exec_ctx_not_flagged(checker, tmp_path):
    """Files that don't reference exec_ctx at all are skipped."""
    no_ctx = tmp_path / "plain_store.py"
    no_ctx.write_text(
        textwrap.dedent(
            """\
            def create(self, tenant_id=""):
                return tenant_id
            """
        ),
        encoding="utf-8",
    )
    issues = checker.check_exec_ctx_precedence(tmp_path)
    assert issues == [], f"Expected no issues for file without exec_ctx, got: {issues}"


def test_multiple_violations_all_reported(checker, tmp_path):
    """All violating lines are reported, not just the first."""
    bad = tmp_path / "multi_bad.py"
    bad.write_text(
        textwrap.dedent(
            """\
            def create(self, exec_ctx=None, **kwargs):
                tenant_id = exec_ctx.tenant_id or kwargs.get("tenant_id")
                run_id = exec_ctx.run_id or kwargs.get("run_id")
            """
        ),
        encoding="utf-8",
    )
    issues = checker.check_exec_ctx_precedence(tmp_path)
    assert len(issues) >= 2, f"Expected at least 2 issues, got: {issues}"


# ---------------------------------------------------------------------------
# Regression: the real codebase must pass after the Wave 10.6 fix
# ---------------------------------------------------------------------------


def test_real_codebase_has_no_exec_ctx_wins(checker):
    """After Wave 10.6, no production writer uses the exec_ctx-wins pattern."""
    root = Path(__file__).parent.parent.parent
    issues = checker.check_exec_ctx_precedence(root / "hi_agent")
    assert issues == [], (
        "exec_ctx-wins violations found in hi_agent/:\n"
        + "\n".join(issues)
    )
