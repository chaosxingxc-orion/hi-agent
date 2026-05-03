"""Tests for scripts/check_layering.py (W31-N3 extended).

Covers:
  - The original ``hi_agent`` / ``agent_kernel`` rule still flags
    ``examples/tests/scripts/docs`` imports.
  - The new ``agent_server/api`` rule flags ``hi_agent`` imports,
    including deferred (function-body) imports, with NO allowlist
    escape valve.
  - Allowlist behaviour preserved on the original roots.
  - The CLI emits JSON when invoked with ``--json``.
  - The real-repo scan PASSES at HEAD.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# expiry_wave: permanent  # added: W31 (governance utility/test helper)
import check_layering as gate


def _make_pkg(parent: Path, name: str, source: str) -> Path:
    pkg = parent / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(source, encoding="utf-8")
    return pkg


def test_extract_imports_picks_up_deferred_imports() -> None:
    """Function-body imports must be reported alongside top-level ones."""
    import ast

    source = (
        "import os\n"
        "def helper():\n"
        "    from hi_agent.config.posture import Posture\n"
        "    return Posture\n"
    )
    tree = ast.parse(source)
    found = gate._extract_imports(tree)
    modules = [m for _, m in found]
    assert "os" in modules
    assert "hi_agent" in modules


def test_check_file_agent_server_no_allowlist(tmp_path: Path, monkeypatch) -> None:
    """W31-N (N.5): agent_server/api scan flags hi_agent even when
    file:line happens to match a (hypothetical) ALLOWLIST entry."""
    # Synthesize a route module that imports hi_agent inline.
    fake = tmp_path / "fake_routes.py"
    fake.write_text(
        "from fastapi import APIRouter\n"
        "def build_router():\n"
        "    from hi_agent.config.posture import Posture\n"
        "    return Posture\n",
        encoding="utf-8",
    )

    # Force REPO_ROOT to tmp_path so relative pathing works.
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    report = gate.LayeringReport(head="test")
    gate.check_file(
        fake,
        report,
        forbidden_prefixes=("hi_agent",),
        allowlist_enabled=False,
    )
    assert report.violations, report
    assert report.violations[0].module == "hi_agent"


def test_check_file_legacy_root_with_allowlist(tmp_path: Path, monkeypatch) -> None:
    """The legacy hi_agent rule still flags examples/tests/etc."""
    fake = tmp_path / "subpkg" / "leaf.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("from examples.demo import Foo\n", encoding="utf-8")

    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    report = gate.LayeringReport(head="test")
    gate.check_file(
        fake,
        report,
        forbidden_prefixes=("examples", "tests", "scripts", "docs"),
        allowlist_enabled=True,
    )
    assert report.violations
    assert report.violations[0].module == "examples"


def test_real_repo_layering_passes() -> None:
    """At HEAD post-W31-N4, the gate must PASS against the real repo."""
    report = gate.run_check()
    assert report.status == "pass", f"Real-repo scan failed: violations={report.violations}"


def test_cli_json_output_pass() -> None:
    """End-to-end: invoking with --json emits a valid JSON report."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_layering.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["check"] == "layering"
    assert payload["status"] == "pass"
    assert "violations" in payload


def test_source_roots_config_covers_agent_server_api() -> None:
    """W31-N3: the new scan root must be in the config."""
    roots = [r for r, _, _ in gate.SOURCE_ROOTS_CONFIG]
    assert "agent_server/api" in roots


def test_agent_server_api_rule_disables_allowlist() -> None:
    """W31-N3: agent_server/api rule must disable the allowlist escape valve."""
    for root, forbidden, allow_enabled in gate.SOURCE_ROOTS_CONFIG:
        if root == "agent_server/api":
            assert "hi_agent" in forbidden
            assert allow_enabled is False
            return
    pytest.fail("agent_server/api root missing from SOURCE_ROOTS_CONFIG")
