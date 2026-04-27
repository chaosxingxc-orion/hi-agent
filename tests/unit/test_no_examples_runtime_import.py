"""Guard: hi_agent package must not import from examples/ at runtime."""
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_hi_agent_does_not_import_examples_at_runtime():
    """Importing hi_agent should never pull in the examples package."""
    script = (
        "import hi_agent, sys\n"
        "hits = [k for k in sys.modules if k.startswith('examples')]\n"
        "assert not hits, f'examples in sys.modules: {hits}'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"


def test_check_layering_script_passes():
    """scripts/check_layering.py must exit 0 at current HEAD."""
    result = subprocess.run(
        [sys.executable, "scripts/check_layering.py"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
