"""W33 Track E.1: tests for the ``check_no_hi_agent_env_direct_read`` gate.

Covers:
  - Allowlist accepts ``hi_agent/config/posture.py`` and
    ``hi_agent/server/ops_routes.py``.
  - The ``check_file`` function detects ``os.environ.get("HI_AGENT_ENV", ...)``
    and ``os.environ["HI_AGENT_ENV"]`` reads in non-allowlisted files.
  - The ``main`` entry point exits 0 on the current repo (post-migration).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_no_hi_agent_env_direct_read.py"


def _load_check_module():
    """Load the gate script as a module so its functions are importable."""
    spec = importlib.util.spec_from_file_location(
        "check_no_hi_agent_env_direct_read", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def check_module():
    return _load_check_module()


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


def test_allowlist_contains_posture_module(check_module) -> None:
    assert "hi_agent/config/posture.py" in check_module._PATH_ALLOWLIST


def test_allowlist_contains_ops_routes_diagnostic_dump(check_module) -> None:
    assert "hi_agent/server/ops_routes.py" in check_module._PATH_ALLOWLIST


# ---------------------------------------------------------------------------
# Violation detection on a synthetic file
# ---------------------------------------------------------------------------


def test_environ_get_call_is_detected(check_module, tmp_path: Path) -> None:
    """A file that calls ``os.environ.get("HI_AGENT_ENV", ...)`` is flagged."""
    sample = tmp_path / "fake_module.py"
    sample.write_text(textwrap.dedent('''\
        import os
        def f():
            return os.environ.get("HI_AGENT_ENV", "dev")
    '''))
    violations = check_module.check_file(sample)
    assert len(violations) == 1
    assert violations[0]["kind"] == "environ.get"
    assert violations[0]["line"] == 3


def test_environ_subscript_is_detected(check_module, tmp_path: Path) -> None:
    """A file that uses ``os.environ["HI_AGENT_ENV"]`` is flagged."""
    sample = tmp_path / "fake_subscript.py"
    sample.write_text(textwrap.dedent('''\
        import os
        def f():
            return os.environ["HI_AGENT_ENV"]
    '''))
    violations = check_module.check_file(sample)
    assert len(violations) == 1
    assert violations[0]["kind"] == "environ[]"


def test_other_env_reads_not_flagged(check_module, tmp_path: Path) -> None:
    """Reads of unrelated env vars are NOT flagged."""
    sample = tmp_path / "ok_module.py"
    sample.write_text(textwrap.dedent('''\
        import os
        def f():
            return os.environ.get("HI_AGENT_PROFILE", "")
    '''))
    violations = check_module.check_file(sample)
    assert violations == []


def test_resolve_runtime_mode_call_is_clean(check_module, tmp_path: Path) -> None:
    """The sanctioned migration pattern produces zero violations."""
    sample = tmp_path / "ok_module.py"
    sample.write_text(textwrap.dedent('''\
        from hi_agent.config.posture import resolve_runtime_mode
        def f():
            return resolve_runtime_mode()
    '''))
    violations = check_module.check_file(sample)
    assert violations == []


# ---------------------------------------------------------------------------
# Path allowlist applies
# ---------------------------------------------------------------------------


def test_allowlisted_path_is_skipped(check_module, monkeypatch) -> None:
    """A file at an allowlisted relative path is skipped even with violations."""
    # Use the posture.py file itself — it intentionally reads HI_AGENT_ENV.
    posture_file = REPO_ROOT / "hi_agent" / "config" / "posture.py"
    violations = check_module.check_file(posture_file)
    assert violations == []


# ---------------------------------------------------------------------------
# Whole-repo current-state assertion
# ---------------------------------------------------------------------------


def test_current_repo_passes_gate() -> None:
    """The post-migration repo MUST pass the gate (exit 0)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, (
        f"check_no_hi_agent_env_direct_read failed: {result.stdout}\n{result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "pass"
    assert payload["violation_count"] == 0
