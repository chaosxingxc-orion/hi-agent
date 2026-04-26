"""Unit test for check_select_completeness script."""
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_select_completeness.py"
ROOT = Path(__file__).parent.parent.parent


def test_check_select_completeness_passes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_select_completeness failed:\n{result.stdout}\n{result.stderr}"
    )


def _import_checker():
    """Import the script as a module to call its helpers directly."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_check_sc", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_checker_on(tmp_path, source: str):
    target = tmp_path / "fake.py"
    target.write_text(textwrap.dedent(source), encoding="utf-8")
    chk = _import_checker()
    chk.ROOT = tmp_path
    return chk.check_spine_call_sites(target)


def test_spine_call_site_check_flags_missing_kwargs(tmp_path):
    """Plain RunFeedback(...) with no spine kwargs and no splat → failure."""
    failures = _run_checker_on(
        tmp_path,
        """
        from hi_agent.evolve.feedback_store import RunFeedback

        def make():
            return RunFeedback(run_id="r1", rating=0.5)
        """,
    )
    assert any("RunFeedback" in f and "tenant_id=" in f for f in failures), failures


def test_spine_call_site_check_skips_splat_expansion(tmp_path):
    """RunFeedback(**fields) is a deserialization site → skipped, not failed."""
    failures = _run_checker_on(
        tmp_path,
        """
        from hi_agent.evolve.feedback_store import RunFeedback

        def hydrate(fields):
            return RunFeedback(**fields)
        """,
    )
    assert failures == [], failures


def test_spine_call_site_check_respects_skip_comment(tmp_path):
    """Trailing '# spine-skip: <reason>' marker exempts the call from the check."""
    failures = _run_checker_on(
        tmp_path,
        """
        from hi_agent.evolve.feedback_store import RunFeedback

        def make():
            return RunFeedback(run_id="r1", rating=0.5)  # spine-skip: legacy migration shim
        """,
    )
    assert failures == [], failures
