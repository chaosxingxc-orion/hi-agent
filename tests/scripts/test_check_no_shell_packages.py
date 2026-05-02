"""Tests for scripts/check_no_shell_packages.py (W31-H8 gate).

Builds a synthetic tmp_path tree mirroring the gate's scan layout
(agent_server/foo/, hi_agent/bar/, ...) and asserts:

  - A bare-shell __init__.py is detected as a violation (FAIL).
  - A bare-shell __init__.py whose first line is `# stub-reason: <text>`
    is tolerated (PASS).
  - A package with peer .py files is not classified as a shell.
  - A package whose __init__.py is large (>= 200 bytes) is not a shell.
  - Multiple shells across both scan roots aggregate correctly.
  - The CLI emits multistatus JSON when invoked with --json --root <tmp>.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Make the script importable as a module.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_no_shell_packages as gate
from _governance.multistatus import GateStatus


def _mkpkg(parent: Path, name: str, init_text: str = "", peers: dict | None = None) -> Path:
    """Create a package directory under parent with given __init__.py text and peers."""
    pkg = parent / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(init_text, encoding="utf-8")
    for fname, body in (peers or {}).items():
        (pkg / fname).write_text(body, encoding="utf-8")
    return pkg


def _scan_roots(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "agent_server"
    h = tmp_path / "hi_agent"
    a.mkdir()
    h.mkdir()
    # Top-level packages carry a peer .py file so they're never themselves
    # classified as shells regardless of __init__.py size.
    (a / "__init__.py").write_text('"""agent_server top."""\n', encoding="utf-8")
    (a / "_top.py").write_text("# placeholder\n", encoding="utf-8")
    (h / "__init__.py").write_text('"""hi_agent top."""\n', encoding="utf-8")
    (h / "_top.py").write_text("# placeholder\n", encoding="utf-8")
    return a, h


def test_bare_shell_fails(tmp_path: Path) -> None:
    a, _ = _scan_roots(tmp_path)
    _mkpkg(a, "shellsub", init_text='"""shellsub subpackage."""\n')
    result = gate.evaluate(tmp_path)
    assert result.status is GateStatus.FAIL
    assert any(
        v["directory"] == "agent_server/shellsub" for v in result.evidence["violations"]
    ), result.evidence
    assert result.evidence["shells_total"] == 1
    assert result.evidence["allowed_shells"] == []


def test_stub_reason_annotation_tolerated(tmp_path: Path) -> None:
    a, _ = _scan_roots(tmp_path)
    _mkpkg(
        a,
        "annotated_shell",
        init_text="# stub-reason: planned-for-W33\n",
    )
    result = gate.evaluate(tmp_path)
    assert result.status is GateStatus.PASS, result.evidence
    allowed = result.evidence["allowed_shells"]
    assert len(allowed) == 1
    assert allowed[0]["directory"] == "agent_server/annotated_shell"
    assert allowed[0]["stub_reason"] == "planned-for-W33"
    assert result.evidence["violations"] == []


def test_package_with_peer_files_not_shell(tmp_path: Path) -> None:
    a, _ = _scan_roots(tmp_path)
    _mkpkg(
        a,
        "real_pkg",
        init_text='"""real_pkg."""\n',
        peers={"impl.py": "def f():\n    return 1\n"},
    )
    result = gate.evaluate(tmp_path)
    assert result.status is GateStatus.PASS, result.evidence
    assert result.evidence["shells_total"] == 0


def test_large_init_not_shell(tmp_path: Path) -> None:
    a, _ = _scan_roots(tmp_path)
    big_text = '"""docstring."""\n' + ("# padding " * 30) + "\n"
    assert len(big_text.encode("utf-8")) >= 200
    _mkpkg(a, "big_init_pkg", init_text=big_text)
    result = gate.evaluate(tmp_path)
    assert result.status is GateStatus.PASS, result.evidence


def test_multiple_shells_across_both_roots(tmp_path: Path) -> None:
    a, h = _scan_roots(tmp_path)
    _mkpkg(a, "as_shell1", init_text='"""x."""\n')
    _mkpkg(a, "as_shell2", init_text='"""y."""\n')
    _mkpkg(h, "ha_shell", init_text='"""z."""\n')
    # And one allowed.
    _mkpkg(h, "ok", init_text="# stub-reason: w33-cleanup\n")
    result = gate.evaluate(tmp_path)
    assert result.status is GateStatus.FAIL
    dirs_violating = sorted(v["directory"] for v in result.evidence["violations"])
    assert dirs_violating == [
        "agent_server/as_shell1",
        "agent_server/as_shell2",
        "hi_agent/ha_shell",
    ]
    allowed_dirs = sorted(s["directory"] for s in result.evidence["allowed_shells"])
    assert allowed_dirs == ["hi_agent/ok"]


def test_pycache_dirs_skipped(tmp_path: Path) -> None:
    """__pycache__ directories must never be classified as shells."""
    a, _ = _scan_roots(tmp_path)
    pyc = a / "__pycache__"
    pyc.mkdir()
    (pyc / "__init__.py").write_text("", encoding="utf-8")  # would be a shell
    result = gate.evaluate(tmp_path)
    assert result.status is GateStatus.PASS, result.evidence


def test_cli_json_output_pass(tmp_path: Path) -> None:
    """End-to-end: invoking the CLI with --json --root prints multistatus JSON."""
    _scan_roots(tmp_path)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_no_shell_packages.py"),
            "--json",
            "--root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["gate"] == "no_shell_packages"
    assert payload["status"] == "PASS"


def test_cli_json_output_fail(tmp_path: Path) -> None:
    a, _ = _scan_roots(tmp_path)
    _mkpkg(a, "shellsub", init_text='"""shellsub."""\n')
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_no_shell_packages.py"),
            "--json",
            "--root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["gate"] == "no_shell_packages"
    assert payload["status"] == "FAIL"
    dirs = [v["directory"] for v in payload["evidence"]["violations"]]
    assert "agent_server/shellsub" in dirs


def test_real_repo_passes() -> None:
    """At HEAD post-W31-H7, the gate must PASS against the real repo."""
    result = gate.evaluate(ROOT)
    assert result.status is GateStatus.PASS, (
        f"Real-repo scan failed: violations={result.evidence.get('violations')}"
    )


@pytest.mark.parametrize("size", [0, 1, 50, 199])
def test_size_threshold_boundary_below(tmp_path: Path, size: int) -> None:
    """Init files strictly below the threshold are shells (when no peers)."""
    a, _ = _scan_roots(tmp_path)
    _mkpkg(a, "boundary", init_text="x" * size)
    result = gate.evaluate(tmp_path)
    assert result.status is GateStatus.FAIL


def test_size_threshold_boundary_at(tmp_path: Path) -> None:
    """Init files at exactly the threshold are NOT shells."""
    a, _ = _scan_roots(tmp_path)
    _mkpkg(a, "boundary_at", init_text="x" * 200)
    result = gate.evaluate(tmp_path)
    assert result.status is GateStatus.PASS
