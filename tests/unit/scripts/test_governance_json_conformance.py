"""Conformance test: every governance check_*.py script supports --json and emits valid JSON."""
import json
import pathlib
import subprocess
import sys

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).parent.parent.parent.parent / "scripts"

# Scripts that MUST support --json
GOVERNANCE_SCRIPTS = [
    "check_agent_kernel_pin.py",
    "check_boundary.py",
    "check_deprecated_field_usage.py",
    "check_doc_consistency.py",
    "check_durable_wiring.py",
    "check_no_research_vocab.py",
    "check_no_wave_tags.py",
    "check_route_scope.py",
    "check_rules.py",
    "check_select_completeness.py",
    "check_validate_before_mutate.py",
]

REQUIRED_FIELDS = {"check", "status", "violations", "head"}


@pytest.mark.parametrize("script", GOVERNANCE_SCRIPTS)
def test_script_emits_valid_json(script):
    """Each governance script must emit parseable JSON with required fields when --json is
    passed."""
    script_path = SCRIPTS_DIR / script
    assert script_path.exists(), f"Script not found: {script_path}"

    result = subprocess.run(
        [sys.executable, str(script_path), "--json"],
        capture_output=True,
        text=True,
        cwd=SCRIPTS_DIR.parent,
        timeout=30,
    )

    # Exit code may be non-zero (failing checks); that's OK
    # But stdout must be valid JSON
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"{script} --json produced invalid JSON: {e}\nSTDOUT: {result.stdout[:500]}")

    missing = REQUIRED_FIELDS - set(data.keys())
    assert not missing, f"{script} JSON missing fields: {missing}"

    valid_statuses = ("pass", "fail", "warn", "not_applicable", "deferred")
    assert data["status"] in valid_statuses, \
        f"{script} JSON status {data['status']!r} not in {valid_statuses}"

    assert isinstance(data["violations"], list), \
        f"{script} JSON violations must be a list"
