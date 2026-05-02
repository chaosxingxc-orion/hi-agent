"""Tests for scripts/check_facade_seams.py (W31-N4 gate).

Covers:
  - An unannotated ``from hi_agent.`` import in a synthesized facade
    file is flagged.
  - Same-line seam annotation passes.
  - Preceding-line seam annotation passes.
  - The bootstrap module is exempt even with raw hi_agent imports.
  - Multiple violations aggregate.
  - The CLI emits multistatus JSON when invoked with ``--json``.
  - The real repo passes at HEAD (post-N.6 annotation patch).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_facade_seams as gate  # noqa: E402  # expiry_wave: permanent  # added: W31 (governance utility/test helper)
from _governance.multistatus import GateStatus  # noqa: E402  # expiry_wave: permanent  # added: W31 (governance utility/test helper)


@pytest.fixture()
def patched_facade_dir(tmp_path: Path, monkeypatch):
    """Override the gate's FACADE_DIR + ROOT to a tmp_path tree."""
    fac_dir = tmp_path / "agent_server" / "facade"
    fac_dir.mkdir(parents=True)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "FACADE_DIR", fac_dir)
    return fac_dir


def test_unannotated_hi_agent_import_fails(patched_facade_dir: Path) -> None:
    fpath = patched_facade_dir / "broken.py"
    fpath.write_text(
        "from __future__ import annotations\n"
        "from hi_agent.config.posture import Posture\n"
        "_ = Posture\n",
        encoding="utf-8",
    )
    result = gate.evaluate()
    assert result.status is GateStatus.FAIL, result.reason
    files = [v["file"] for v in result.evidence["violations"]]
    assert "agent_server/facade/broken.py" in files


def test_same_line_seam_annotation_passes(patched_facade_dir: Path) -> None:
    fpath = patched_facade_dir / "ok_inline.py"
    fpath.write_text(
        "from hi_agent.server.idempotency import IdempotencyStore  # r-as-1-seam: persistence boundary\n"
        "_ = IdempotencyStore\n",
        encoding="utf-8",
    )
    result = gate.evaluate()
    assert result.status is GateStatus.PASS, result.evidence


def test_preceding_line_seam_annotation_passes(patched_facade_dir: Path) -> None:
    fpath = patched_facade_dir / "ok_preceding.py"
    fpath.write_text(
        "# r-as-1-seam: persistence boundary\n"
        "from hi_agent.server.idempotency import IdempotencyStore\n"
        "_ = IdempotencyStore\n",
        encoding="utf-8",
    )
    result = gate.evaluate()
    assert result.status is GateStatus.PASS, result.evidence


def test_blank_line_between_seam_and_import_passes(patched_facade_dir: Path) -> None:
    """A blank line between the annotation and the import is tolerated."""
    fpath = patched_facade_dir / "ok_blank_line.py"
    fpath.write_text(
        "# r-as-1-seam: persistence boundary\n"
        "\n"
        "from hi_agent.server.idempotency import IdempotencyStore\n"
        "_ = IdempotencyStore\n",
        encoding="utf-8",
    )
    result = gate.evaluate()
    assert result.status is GateStatus.PASS, result.evidence


def test_multiple_violations_aggregate(patched_facade_dir: Path) -> None:
    fpath = patched_facade_dir / "double.py"
    fpath.write_text(
        "from hi_agent.config.posture import Posture\n"
        "from hi_agent.server.idempotency import IdempotencyStore\n",
        encoding="utf-8",
    )
    result = gate.evaluate()
    assert result.status is GateStatus.FAIL
    assert len(result.evidence["violations"]) == 2


def test_bootstrap_module_exempt(tmp_path: Path, monkeypatch) -> None:
    """W31-N1 reserves bootstrap.py as the canonical seam; it must
    not require r-as-1-seam comments even with hi_agent imports."""
    fac_dir = tmp_path / "agent_server" / "facade"
    fac_dir.mkdir(parents=True)
    bootstrap = tmp_path / "agent_server" / "bootstrap.py"
    bootstrap.write_text(
        "from hi_agent.config.posture import Posture\n"
        "_ = Posture\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "FACADE_DIR", fac_dir)
    # bootstrap is outside FACADE_DIR — gate doesn't even scan it. The
    # exemption matters when bootstrap appears INSIDE FACADE_DIR (e.g.
    # via a future move). Synthesise that case explicitly.
    inside = fac_dir / "bootstrap_relocated.py"
    inside.write_text(
        "from hi_agent.config.posture import Posture\n",
        encoding="utf-8",
    )
    # Add bootstrap relpath to the EXEMPT list for the duration of the test.
    monkeypatch.setattr(
        gate,
        "EXEMPT_FILES",
        frozenset({"agent_server/facade/bootstrap_relocated.py"}),
    )
    result = gate.evaluate()
    assert result.status is GateStatus.PASS, result.evidence


def test_cli_json_pass() -> None:
    """End-to-end: --json on the real repo emits a multistatus payload."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_facade_seams.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["gate"] == "facade_seams"
    assert payload["status"] == "PASS"


def test_real_repo_passes() -> None:
    """At HEAD post-W31-N4 annotation patch, the gate must PASS."""
    result = gate.evaluate()
    assert result.status is GateStatus.PASS, (
        f"Real-repo scan failed: violations={result.evidence.get('violations')}"
    )
