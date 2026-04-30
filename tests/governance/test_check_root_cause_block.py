# tests/governance/test_check_root_cause_block.py
import subprocess
import sys
import textwrap


def test_script_exists_and_runs():
    result = subprocess.run(
        [sys.executable, "scripts/check_root_cause_block.py", "--base", "HEAD", "--head", "HEAD", "--json"],
        capture_output=True, text=True, cwd=".",
    )
    # HEAD..HEAD has no commits, so should pass
    assert result.returncode == 0
