"""Tests for scripts/check_rules.py (DF-42 CLAUDE.md rule enforcement)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_rules.py"


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(root), *extra],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _make_fake_repo(tmp_path: Path) -> Path:
    """Create minimal hi_agent/ + agent_kernel/ trees under tmp_path."""
    (tmp_path / "hi_agent").mkdir()
    (tmp_path / "agent_kernel").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "hi_agent" / "config").mkdir()
    return tmp_path


def test_check_rules_script_exists_and_imports():
    """Script file must exist at the documented location."""
    assert SCRIPT.exists(), f"check_rules.py missing at {SCRIPT}"
    # And must be syntactically valid Python.
    compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec")


def test_check_rules_script_runs_on_current_head():
    """Running against the real repo completes without Python errors.

    DF-44 is expected to be closed by the time this test passes, so the
    current repository must produce a clean hard-rule pass.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Expected a clean pass; got {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "Rule 6" in result.stdout
    assert "[PASS] Rule 5" in result.stdout
    assert "[PASS] Rule 13" in result.stdout
    assert "Rule 5" in result.stdout
    assert "OVERALL" in result.stdout


def test_check_rules_detects_rule13_inline_fallback(tmp_path):
    """Planted ' or InMemoryStore(' pattern must flag as Rule 13 FAIL."""
    root = _make_fake_repo(tmp_path)
    (root / "hi_agent" / "mod.py").write_text(
        textwrap.dedent(
            """
            class A:
                def __init__(self, store=None):
                    self._store = store or InMemoryStore()
            """
        ).lstrip(),
        encoding="utf-8",
    )
    result = _run(root)
    assert result.returncode == 1
    assert "Rule 13" in result.stdout
    assert "InMemoryStore" in result.stdout


def test_rule5_entrypoint_allowlist_no_false_positive(tmp_path):
    """asyncio.run inside a function named `main` must NOT be flagged."""
    root = _make_fake_repo(tmp_path)
    (root / "hi_agent" / "clean.py").write_text(
        textwrap.dedent(
            """
            import asyncio

            async def work():
                return 1

            def main():
                asyncio.run(work())
            """
        ).lstrip(),
        encoding="utf-8",
    )
    result = _run(root)
    # No hard-rule failures expected on this clean fake repo.
    assert result.returncode == 0, (
        f"Expected PASS on clean repo; got {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "[PASS] Rule 5" in result.stdout


def test_language_rule_flags_cjk_in_prompt_assignment(tmp_path):
    """CJK characters assigned to a `prompt=` identifier must be flagged."""
    root = _make_fake_repo(tmp_path)
    # Note: this test file itself intentionally contains a CJK literal in the
    # generated source, NOT in this test's own module body.
    src = 'prompt = "\u4f60\u597d"\n'  # "你好"
    (root / "hi_agent" / "bad_prompt.py").write_text(src, encoding="utf-8")
    result = _run(root)
    assert result.returncode == 1
    assert "Language Rule" in result.stdout
    assert "CJK" in result.stdout
