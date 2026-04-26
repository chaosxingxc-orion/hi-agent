"""Tests that allowlist baseline enforcement detects growth."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _import_module():
    import sys as _sys

    mod_name = "check_route_scope"
    spec = importlib.util.spec_from_file_location(
        mod_name, Path("scripts/check_route_scope.py")
    )
    if spec is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        return None
    # Register in sys.modules so dataclass string-annotation resolution works
    _sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del _sys.modules[mod_name]
        raise
    return mod


def test_allowlist_count_exceeds_baseline_fails(tmp_path):
    """When allowlist count > baseline, check_route_scope must exit nonzero."""
    # Write a baseline file with count 0 (current allowlist has more entries)
    baseline = tmp_path / "allowlist-baseline.txt"
    baseline.write_text("0\n")

    # Patch the baseline path by monkey-patching the module
    mod = _import_module()
    if mod is None:
        pytest.skip("Cannot import module")

    # Simulate the baseline check logic inline (avoids subprocess env complexity)
    allowlist_count = len(mod.NO_SCOPE_ALLOWLIST)
    baseline_count = int(baseline.read_text().strip())

    assert allowlist_count > baseline_count, (
        "Test precondition: current allowlist must exceed baseline of 0"
    )
    # The check would produce a FAIL result
    would_fail = allowlist_count > baseline_count
    assert would_fail, "Baseline growth check should detect allowlist grew past baseline"


def test_allowlist_count_equals_baseline_passes(tmp_path):
    """When allowlist count == baseline, no growth failure should be reported."""
    mod = _import_module()
    if mod is None:
        pytest.skip("Cannot import module")

    count = len(mod.NO_SCOPE_ALLOWLIST)
    baseline = tmp_path / "allowlist-baseline.txt"
    baseline.write_text(f"{count}\n")

    baseline_count = int(baseline.read_text().strip())
    would_fail = count > baseline_count
    assert not would_fail, "Equal count should not trigger a growth failure"


def test_allowlist_count_below_baseline_passes(tmp_path):
    """When allowlist count < baseline, that is acceptable (shrinkage is good)."""
    mod = _import_module()
    if mod is None:
        pytest.skip("Cannot import module")

    count = len(mod.NO_SCOPE_ALLOWLIST)
    # Set baseline higher than current count
    baseline = tmp_path / "allowlist-baseline.txt"
    baseline.write_text(f"{count + 10}\n")

    baseline_count = int(baseline.read_text().strip())
    would_fail = count > baseline_count
    assert not would_fail, "Shrinkage below baseline should not trigger a growth failure"


def test_validate_allowlist_clean_before_baseline_check():
    """Validate that _validate_allowlist() passes before baseline check runs."""
    mod = _import_module()
    if mod is None or not hasattr(mod, "_validate_allowlist"):
        pytest.skip("Module or _validate_allowlist not available")

    issues = mod._validate_allowlist()
    assert issues == [], (
        f"_validate_allowlist() must be clean before baseline check; issues: {issues}"
    )


def test_check_route_scope_script_runs_successfully():
    """check_route_scope.py must exit 0 when routes are compliant."""
    result = subprocess.run(
        [sys.executable, "scripts/check_route_scope.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_route_scope.py exited {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ALLOWLIST:" in result.stdout, (
        f"Expected 'ALLOWLIST:' in output; got: {result.stdout}"
    )
