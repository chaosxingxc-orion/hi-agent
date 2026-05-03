"""Tests for scripts/check_no_hardcoded_wave.py (W14-A4 gate, W32-D D.2 extension).

Covers:
  - The gate scans hi_agent/ and agent_server/ in addition to scripts/ and tests/
    (W32-D D.2 scan-dir extension).
  - A `# expiry_wave: Wave N` annotation on a code line is exempt (compat-shim
    pattern used in hi_agent/errors/__init__.py and similar files).
  - A `# wave-literal-ok` line marker exempts a line.
  - A bare quoted "Wave N" string literal in a code path is rejected.
  - The real repository at HEAD passes (production code carries no
    inline string-literal Wave-N hits).
  - The CLI emits machine-readable JSON when invoked with --json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest  # noqa: F401  # expiry_wave: permanent

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "check_no_hardcoded_wave.py"
sys.path.insert(0, str(ROOT / "scripts"))
import check_no_hardcoded_wave as gate


def _run_gate_in(scan_root: Path, *, exempt_self: bool = True) -> tuple[int, dict]:
    """Run the gate against a synthetic root via subprocess.

    Uses a small inline runner that overrides ``_SCAN_DIRS`` and ``ROOT`` to
    point at ``scan_root`` so the test does not depend on the real repo
    layout. Returns (returncode, parsed JSON payload).
    """
    runner = (
        "import json, pathlib, sys\n"
        "sys.path.insert(0, r'" + str(ROOT / "scripts") + "')\n"
        "import check_no_hardcoded_wave as gate\n"
        "scan_root = pathlib.Path(r'" + str(scan_root) + "')\n"
        "gate.ROOT = scan_root.parent\n"
        "gate._SCAN_DIRS = (scan_root,)\n"
        "sys.argv = ['check_no_hardcoded_wave.py', '--json']\n"
        "rc = gate.main()\n"
        "sys.exit(rc)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", runner],
        capture_output=True,
        text=True,
        check=False,
    )
    payload: dict = {}
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {"raw_stdout": proc.stdout, "raw_stderr": proc.stderr}
    return proc.returncode, payload


def test_scan_dirs_includes_hi_agent_and_agent_server() -> None:
    """W32-D D.2: scan dirs must include hi_agent/ and agent_server/."""
    scanned = {p.name for p in gate._SCAN_DIRS}
    assert "hi_agent" in scanned, scanned
    assert "agent_server" in scanned, scanned
    # Pre-existing scan dirs preserved.
    assert "scripts" in scanned, scanned
    assert "tests" in scanned, scanned


def test_real_repo_passes_at_head() -> None:
    """Production code at HEAD must not contain any inline `"Wave N"` literals."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"check_no_hardcoded_wave failed at HEAD\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    payload = json.loads(proc.stdout)
    assert payload["status"] == "pass", payload
    assert payload["issues_found"] == 0, payload


def test_quoted_wave_literal_in_synthetic_file_is_caught(tmp_path: Path) -> None:
    """A bare ``"Wave N"`` string literal in synthetic production code is flagged."""
    synth_root = tmp_path / "hi_agent"
    synth_root.mkdir()
    bad_file = synth_root / "bad_module.py"
    # Build the literal at runtime so the test source itself is not a wave hit.
    label_line = '_LABEL = ' + chr(34) + 'Wave 99' + chr(34) + '\n'
    bad_file.write_text(
        '"""Synthetic module."""\n' + label_line,
        encoding="utf-8",
    )
    rc, payload = _run_gate_in(synth_root)
    assert rc == 1, payload
    assert payload.get("status") == "fail", payload
    assert payload.get("issues_found", 0) >= 1, payload


def test_inline_expiry_wave_marker_is_exempt(tmp_path: Path) -> None:
    """``# expiry_wave: Wave N`` on a code line is the documented compat-shim
    pattern used by hi_agent/errors/__init__.py and similar; the gate must not
    fire on these annotated lines."""
    synth_root = tmp_path / "hi_agent"
    synth_root.mkdir()
    shim_file = synth_root / "shim.py"
    # Mirror the actual pattern in hi_agent/errors/__init__.py:19.
    shim_file.write_text(
        '"""Compat shim (synthetic)."""\n'
        'from hi_agent.contracts.errors import *  # noqa: F401  # expiry_wave: Wave 99\n',
        encoding="utf-8",
    )
    rc, payload = _run_gate_in(synth_root)
    assert rc == 0, payload
    assert payload.get("status") == "pass", payload


def test_wave_literal_ok_marker_is_exempt(tmp_path: Path) -> None:
    """A trailing ``# wave-literal-ok`` comment exempts an otherwise-rejected literal."""
    synth_root = tmp_path / "scripts"
    synth_root.mkdir()
    ok_file = synth_root / "ok_literal.py"
    label_line = (
        '_LABEL = ' + chr(34) + 'Wave 99' + chr(34) + '  # wave-literal-ok\n'
    )
    ok_file.write_text(
        '"""Synthetic script."""\n' + label_line,
        encoding="utf-8",
    )
    rc, payload = _run_gate_in(synth_root)
    assert rc == 0, payload
    assert payload.get("status") == "pass", payload


def test_cli_json_output_shape() -> None:
    """`--json` must emit a parseable JSON document with the expected keys."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(proc.stdout)
    assert "status" in payload
    assert "check" in payload and payload["check"] == "no_hardcoded_wave"
    assert "issues_found" in payload
    assert "issues" in payload
    assert isinstance(payload["issues"], list)
