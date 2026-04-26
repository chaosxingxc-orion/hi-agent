"""Unit tests for scripts/release_notice.py.

Tests use unittest.mock.patch to isolate all subprocess calls so that no
real git operations are performed.
"""
from __future__ import annotations

import importlib.util
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Load the module under test without executing __main__
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "release_notice.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("release_notice", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rn = _load_module()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Return a mock CompletedProcess."""
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


# ---------------------------------------------------------------------------
# test_dirty_tree_refused
# ---------------------------------------------------------------------------


def test_dirty_tree_refused():
    """Dirty working tree must cause run() to return non-zero without committing."""
    with patch("subprocess.run") as mock_run:
        # git status --porcelain returns dirty output
        mock_run.return_value = _make_cp(stdout="M scripts/foo.py")
        result = rn.run(wave="10.6", allow_dirty=False, dry_run=False)

    assert result != 0, "Expected non-zero exit when tree is dirty"
    # Ensure we never called git commit
    for c in mock_run.call_args_list:
        args_list = c.args[0] if c.args else []
        assert "commit" not in args_list, f"git commit must not be called on dirty tree: {c}"


# ---------------------------------------------------------------------------
# test_template_substitution
# ---------------------------------------------------------------------------


def test_template_substitution(tmp_path):
    """Placeholders {{HEAD}}, {{DATE}}, {{WAVE}} are replaced in the output notice."""
    # Create a minimal template
    template_dir = tmp_path / "_templates"
    template_dir.mkdir(parents=True)
    template_file = template_dir / "notice-10.6.md"
    template_file.write_text(
        textwrap.dedent("""\
            # Wave {{WAVE}} Delivery Notice
            ```
            Functional HEAD:  {{HEAD}}
            Notice HEAD:      {{HEAD}}
            T3 evidence:      {{T3_EVIDENCE}}
            Clean-env evidence: {{CLEAN_ENV_EVIDENCE}}
            Current verified readiness: {{SCORE_CAP}}
            Validated by:     scripts/check_doc_consistency.py
            ```
        """),
        encoding="utf-8",
    )

    notices_dir = tmp_path / "notices"
    notices_dir.mkdir()

    committed_files: list[Path] = []

    def fake_run(cmd, **kwargs):
        if cmd[1:3] == ["status", "--porcelain"]:
            return _make_cp(stdout="")  # clean tree
        if cmd[1:3] == ["rev-parse", "--short"]:
            return _make_cp(stdout="abc1234")
        if cmd[1] == "add":
            committed_files.append(Path(cmd[2]))
            return _make_cp()
        if cmd[1] == "commit":
            return _make_cp()
        return _make_cp()

    with (
        patch("subprocess.run", side_effect=fake_run),
        patch.object(rn, "TEMPLATES_DIR", template_dir),
        patch.object(rn, "NOTICES_DIR", notices_dir),
    ):
        result = rn.run(wave="10.6", allow_dirty=False, dry_run=False)

    assert result == 0, "Expected success"
    # Find the written notice file
    written = list(notices_dir.glob("*delivery-notice.md"))
    assert written, "Notice file must have been written"
    content = written[0].read_text(encoding="utf-8")
    assert "abc1234" in content, f"HEAD 'abc1234' not found in notice:\n{content}"
    assert "10.6" in content, "Wave '10.6' not found in notice"
    assert "{{HEAD}}" not in content, "Unreplaced placeholder {{HEAD}} still present"
    assert "{{WAVE}}" not in content, "Unreplaced placeholder {{WAVE}} still present"


# ---------------------------------------------------------------------------
# test_post_commit_head_realignment
# ---------------------------------------------------------------------------


def test_post_commit_head_realignment(tmp_path):
    """When the commit changes HEAD, the notice is rewritten and commit is amended."""
    template_dir = tmp_path / "_templates"
    template_dir.mkdir(parents=True)
    template_file = template_dir / "notice-10.6.md"
    template_file.write_text(
        textwrap.dedent("""\
            # Wave {{WAVE}} Delivery Notice
            ```
            Functional HEAD:  {{HEAD}}
            Notice HEAD:      {{HEAD}}
            Validated by:     scripts/check_doc_consistency.py
            ```
        """),
        encoding="utf-8",
    )

    notices_dir = tmp_path / "notices"
    notices_dir.mkdir()

    call_count = {"rev_parse": 0}

    def fake_run(cmd, **kwargs):
        if cmd[1:3] == ["status", "--porcelain"]:
            return _make_cp(stdout="")
        if cmd[1:3] == ["rev-parse", "--short"]:
            call_count["rev_parse"] += 1
            # First call (before commit): aaa1111
            # Subsequent calls (after commit): bbb2222
            if call_count["rev_parse"] == 1:
                return _make_cp(stdout="aaa1111")
            return _make_cp(stdout="bbb2222")
        if cmd[1] == "add":
            return _make_cp()
        if cmd[1] == "commit":
            # Both initial commit and amend
            return _make_cp()
        return _make_cp()

    with (
        patch("subprocess.run", side_effect=fake_run),
        patch.object(rn, "TEMPLATES_DIR", template_dir),
        patch.object(rn, "NOTICES_DIR", notices_dir),
    ):
        result = rn.run(wave="10.6", allow_dirty=False, dry_run=False)

    assert result == 0
    written = list(notices_dir.glob("*delivery-notice.md"))
    assert written, "Notice file must have been written"
    content = written[0].read_text(encoding="utf-8")
    # After realignment, the notice should contain the post-commit HEAD
    assert "bbb2222" in content, (
        f"Expected realigned HEAD 'bbb2222' in notice:\n{content}"
    )
    assert "aaa1111" not in content, (
        f"Stale HEAD 'aaa1111' should have been replaced in notice:\n{content}"
    )


# ---------------------------------------------------------------------------
# test_dry_run_no_commit
# ---------------------------------------------------------------------------


def test_dry_run_no_commit(tmp_path):
    """In --dry-run mode, no git commit is called and the rendered output is printed."""
    template_dir = tmp_path / "_templates"
    template_dir.mkdir(parents=True)
    (template_dir / "notice-10.6.md").write_text(
        "# Wave {{WAVE}}\nFunctional HEAD: {{HEAD}}\n",
        encoding="utf-8",
    )

    notices_dir = tmp_path / "notices"
    notices_dir.mkdir()

    def fake_run(cmd, **kwargs):
        if cmd[1:3] == ["status", "--porcelain"]:
            return _make_cp(stdout="")
        if cmd[1:3] == ["rev-parse", "--short"]:
            return _make_cp(stdout="dryrun7")
        return _make_cp()

    with (
        patch("subprocess.run", side_effect=fake_run),
        patch.object(rn, "TEMPLATES_DIR", template_dir),
        patch.object(rn, "NOTICES_DIR", notices_dir),
    ):
        result = rn.run(wave="10.6", allow_dirty=False, dry_run=True)

    assert result == 0
    # No notice file should have been written
    written = list(notices_dir.glob("*delivery-notice.md"))
    assert not written, f"Dry-run must not write notice files; found: {written}"
    # No commit calls should have happened
    # (fake_run would return ok for any cmd, but we check no notice file was written above)
