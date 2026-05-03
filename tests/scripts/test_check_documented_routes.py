"""Tests for scripts/check_documented_routes.py (W31-N7 gate).

Covers:
  - The real repo passes at HEAD (post-N.7 reconciliation).
  - A synthesized doc + routes tree where a route is decorated but
    undocumented yields a FAIL.
  - A synthesized doc + routes tree where a route is documented but
    undecorated yields a FAIL.
  - Backlog-listed routes do NOT trigger an undocumented-decorated FAIL
    (they are explicitly excluded from the comparison).
  - Router prefix is resolved correctly so /{run_id}/cancel inside an
    APIRouter(prefix='/v1/runs') becomes /v1/runs/{run_id}/cancel.
  - app.get('/v1/health') in __init__.py is picked up.
  - The CLI emits multistatus JSON when invoked with --json.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
# expiry_wave: permanent  # added: W31 (governance utility/test helper)
import check_documented_routes as gate
from _governance.multistatus import (
    GateStatus,  # expiry_wave: permanent  # added: W31 (governance utility/test helper)
)


def _make_doc(
    tmp_path: Path, released: list[tuple[str, str]], backlog: list[tuple[str, str]]
) -> Path:
    """Synthesize a contract doc with §2 + §13 sections."""
    doc = tmp_path / "doc.md"
    lines = [
        "# Contract",
        "",
        "## 2. Released routes",
        "",
        "| Method | Path | M |",
        "|---|---|---|",
    ]
    for method, path in released:
        lines.append(f"| {method} | {path} | x |")
    lines += ["", "## 13. v1.1 — not yet implemented", "", "| Method | Path | M |", "|---|---|---|"]
    for method, path in backlog:
        lines.append(f"| {method} | {path} | x |")
    lines.append("")
    doc.write_text("\n".join(lines), encoding="utf-8")
    return doc


def _make_routes_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    rd = tmp_path / "agent_server" / "api"
    rd.mkdir(parents=True)
    for name, content in files.items():
        (rd / name).write_text(content, encoding="utf-8")
    # Init might be needed
    if "__init__.py" not in files:
        (rd / "__init__.py").write_text("", encoding="utf-8")
    return rd


def test_real_repo_passes() -> None:
    """At HEAD post-N.7 reconciliation, the gate must PASS."""
    result = gate.evaluate()
    assert result.status is GateStatus.PASS, f"Real-repo scan failed: {result.evidence}"


def test_decorated_but_undocumented_fails(tmp_path: Path, monkeypatch) -> None:
    """A route the server exposes but the doc doesn't mention is a FAIL."""
    doc = _make_doc(tmp_path, released=[("POST", "/v1/runs")], backlog=[])
    rd = _make_routes_dir(
        tmp_path,
        {
            "routes_runs.py": (
                "from fastapi import APIRouter\n"
                "def build_router():\n"
                "    router = APIRouter(prefix='/v1/runs')\n"
                "    @router.post('')\n"
                "    async def post_run():\n"
                "        return {}\n"
                "    @router.post('/{rid}/secret_route')\n"
                "    async def secret():\n"
                "        return {}\n"
                "    return router\n"
            ),
        },
    )
    monkeypatch.setattr(gate, "CONTRACT_DOC", doc)
    monkeypatch.setattr(gate, "ROUTES_DIR", rd)
    result = gate.evaluate()
    assert result.status is GateStatus.FAIL, result.reason
    paths = [r["path"] for r in result.evidence["undocumented_decorated"]]
    assert "/v1/runs/{rid}/secret_route" in paths


def test_documented_but_undecorated_fails(tmp_path: Path, monkeypatch) -> None:
    """The doc promising a non-existent surface is a FAIL."""
    doc = _make_doc(
        tmp_path,
        released=[("POST", "/v1/runs"), ("GET", "/v1/runs/{rid}")],
        backlog=[],
    )
    rd = _make_routes_dir(
        tmp_path,
        {
            "routes_runs.py": (
                "from fastapi import APIRouter\n"
                "def build_router():\n"
                "    router = APIRouter(prefix='/v1/runs')\n"
                "    @router.post('')\n"
                "    async def post_run():\n"
                "        return {}\n"
                "    return router\n"
            ),
        },
    )
    monkeypatch.setattr(gate, "CONTRACT_DOC", doc)
    monkeypatch.setattr(gate, "ROUTES_DIR", rd)
    result = gate.evaluate()
    assert result.status is GateStatus.FAIL, result.reason
    paths = [r["path"] for r in result.evidence["released_without_handler"]]
    assert "/v1/runs/{rid}" in paths


def test_backlog_excludes_undocumented_check(tmp_path: Path, monkeypatch) -> None:
    """Backlog rows must NOT count as 'undocumented decorated' even if no handler."""
    doc = _make_doc(
        tmp_path,
        released=[("POST", "/v1/runs")],
        backlog=[("GET", "/v1/runs/{rid}")],  # backlog mention only
    )
    rd = _make_routes_dir(
        tmp_path,
        {
            "routes_runs.py": (
                "from fastapi import APIRouter\n"
                "def build_router():\n"
                "    router = APIRouter(prefix='/v1/runs')\n"
                "    @router.post('')\n"
                "    async def post_run():\n"
                "        return {}\n"
                "    return router\n"
            ),
        },
    )
    monkeypatch.setattr(gate, "CONTRACT_DOC", doc)
    monkeypatch.setattr(gate, "ROUTES_DIR", rd)
    result = gate.evaluate()
    assert result.status is GateStatus.PASS, result.evidence


def test_app_level_decoration_picked_up(tmp_path: Path, monkeypatch) -> None:
    """W31-N7: @app.get('/v1/health') in __init__.py is included."""
    doc = _make_doc(tmp_path, released=[("GET", "/v1/health")], backlog=[])
    rd = _make_routes_dir(
        tmp_path,
        {
            "__init__.py": (
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n"
                "@app.get('/v1/health')\n"
                "async def _health():\n"
                "    return {'status': 'ok'}\n"
            ),
        },
    )
    monkeypatch.setattr(gate, "CONTRACT_DOC", doc)
    monkeypatch.setattr(gate, "ROUTES_DIR", rd)
    result = gate.evaluate()
    assert result.status is GateStatus.PASS, result.evidence


def test_router_prefix_resolved(tmp_path: Path, monkeypatch) -> None:
    """The APIRouter(prefix=...) is concatenated with the decorator path."""
    doc = _make_doc(
        tmp_path,
        released=[("POST", "/v1/gates/{gid}/decide")],
        backlog=[],
    )
    rd = _make_routes_dir(
        tmp_path,
        {
            "routes_gates.py": (
                "from fastapi import APIRouter\n"
                "def build_router():\n"
                "    router = APIRouter(prefix='/v1/gates')\n"
                "    @router.post('/{gid}/decide')\n"
                "    async def decide():\n"
                "        return {}\n"
                "    return router\n"
            ),
        },
    )
    monkeypatch.setattr(gate, "CONTRACT_DOC", doc)
    monkeypatch.setattr(gate, "ROUTES_DIR", rd)
    result = gate.evaluate()
    assert result.status is GateStatus.PASS, result.evidence


def test_cli_json_pass() -> None:
    """End-to-end: --json on the real repo emits a multistatus payload."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_documented_routes.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["gate"] == "documented_routes"
    assert payload["status"] == "PASS"
