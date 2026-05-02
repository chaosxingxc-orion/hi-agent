#!/usr/bin/env python
"""W31-N (N.7): documented-route consistency gate.

Validates that the §2 "Released routes" section of
``docs/platform/agent-server-northbound-contract-v1.md`` is in sync with
the routes actually decorated under ``agent_server/api/routes_*.py``.

Two failure modes:
  1. A route is decorated under ``agent_server/api/routes_*.py`` but is
     NOT listed in the §2 "Released routes" table — downstream cannot
     discover it.
  2. A route is listed in the §2 "Released routes" table but is NOT
     decorated under ``agent_server/api/routes_*.py`` — the document
     promises a surface the server does not honour.

Routes listed in the §13 "v1.1 — not yet implemented" backlog table are
explicitly excluded from the comparison: they are documented as NOT
released and the gate must not flag them.

Usage::

    python scripts/check_documented_routes.py            # human-readable
    python scripts/check_documented_routes.py --json     # multistatus JSON

Exit 0 = PASS; 1 = FAIL.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DOC = ROOT / "docs" / "platform" / "agent-server-northbound-contract-v1.md"
ROUTES_DIR = ROOT / "agent_server" / "api"

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit  # noqa: E402  # expiry_wave: permanent  # added: W31 (governance utility/test helper)

_DECORATOR_PATTERN = re.compile(r"^\s*@router\.(get|post|put|delete|patch)\((.+)\)")
# Route table rows look like:
#   | METHOD | /v1/path | ... |
_DOC_ROW_PATTERN = re.compile(
    r"^\s*\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|\s*(/[A-Za-z0-9_\-{}/]+)\s*\|"
)
_RELEASED_HEADER_PATTERN = re.compile(r"^##\s*\d+\.\s+Released routes")
_BACKLOG_HEADER_PATTERN = re.compile(r"^##\s*\d+\.\s+v1\.1\s")
_NEXT_SECTION_PATTERN = re.compile(r"^##\s")


def _normalize_path(path: str) -> str:
    return path.strip().rstrip("/")


def _collect_decorated_routes_from_file(
    py_file: Path,
) -> set[tuple[str, str]]:
    """Return decorated routes from a single .py file.

    Picks up both ``@router.<method>(...)`` (with optional APIRouter prefix
    resolved by AST) AND ``@app.<method>(...)`` decorations so the
    standalone ``GET /v1/health`` endpoint defined in ``api/__init__.py``
    is included.
    """
    routes: set[tuple[str, str]] = set()
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (OSError, SyntaxError):
        return routes

    # First pass: find APIRouter(prefix=...) literal (router prefix only;
    # @app.<method> decorations are taken at face value).
    prefix = ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Name) and node.func.id == "APIRouter"
        ):
            continue
        for kw in node.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                prefix = str(kw.value.value).rstrip("/")
                break
        if prefix:
            break

    # Second pass: collect decorator paths.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            func = deco.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in {"router", "app"}
                and func.attr in {"get", "post", "put", "delete", "patch"}
            ):
                continue
            method = func.attr.upper()
            target = func.value.id
            if not deco.args or not isinstance(deco.args[0], ast.Constant):
                continue
            rel_path = str(deco.args[0].value)
            if target == "app":
                # Standalone app decoration: path is absolute as-given.
                full_path = rel_path
            else:
                full_path = f"{prefix}{rel_path}".rstrip("/")
                if not full_path.startswith("/"):
                    full_path = f"/{full_path}"
            routes.add((method, _normalize_path(full_path)))
    return routes


def _collect_decorated_routes() -> set[tuple[str, str]]:
    """Return {(METHOD, full_path)} for every decorator under agent_server/api/.

    Scans ``routes_*.py`` (router-prefixed) and ``__init__.py`` (app-level
    decorations like the /v1/health endpoint).
    """
    routes: set[tuple[str, str]] = set()
    if not ROUTES_DIR.exists():
        return routes

    for py_file in ROUTES_DIR.rglob("routes_*.py"):
        routes |= _collect_decorated_routes_from_file(py_file)
    init_py = ROUTES_DIR / "__init__.py"
    if init_py.exists():
        routes |= _collect_decorated_routes_from_file(init_py)
    return routes


def _collect_documented_routes() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Return (released_routes, backlog_routes) parsed from the contract doc.

    Released routes are read from the §2 "Released routes" section.
    Backlog routes are read from the §13 "v1.1 — not yet implemented"
    section and excluded from the comparison.
    """
    if not CONTRACT_DOC.exists():
        return set(), set()
    lines = CONTRACT_DOC.read_text(encoding="utf-8").splitlines()

    section: str = ""  # "" | "released" | "backlog"
    released: set[tuple[str, str]] = set()
    backlog: set[tuple[str, str]] = set()
    for raw in lines:
        if _RELEASED_HEADER_PATTERN.match(raw):
            section = "released"
            continue
        if _BACKLOG_HEADER_PATTERN.match(raw):
            section = "backlog"
            continue
        if _NEXT_SECTION_PATTERN.match(raw) and section in {"released", "backlog"}:
            section = ""
            continue
        if section == "":
            continue
        m = _DOC_ROW_PATTERN.match(raw)
        if not m:
            continue
        method = m.group(1).upper()
        path = _normalize_path(m.group(2))
        if section == "released":
            released.add((method, path))
        elif section == "backlog":
            backlog.add((method, path))
    return released, backlog


def evaluate() -> GateResult:
    if not CONTRACT_DOC.exists():
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="documented_routes",
            reason=f"contract doc not found: {CONTRACT_DOC.relative_to(ROOT)}",
            evidence={"doc_path": str(CONTRACT_DOC.relative_to(ROOT))},
        )
    released_doc, backlog_doc = _collect_documented_routes()
    decorated = _collect_decorated_routes()

    # Released-but-not-decorated: doc promises a surface the server doesn't honour.
    released_without_handler = sorted(released_doc - decorated)
    # Decorated-but-not-released-and-not-backlog: surface exists but is undocumented.
    undocumented_decorated = sorted(decorated - released_doc - backlog_doc)

    if released_without_handler or undocumented_decorated:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="documented_routes",
            reason=(
                f"documented-route mismatch: "
                f"{len(released_without_handler)} released-without-handler, "
                f"{len(undocumented_decorated)} decorated-but-undocumented"
            ),
            evidence={
                "released_without_handler": [
                    {"method": m, "path": p} for m, p in released_without_handler
                ],
                "undocumented_decorated": [
                    {"method": m, "path": p} for m, p in undocumented_decorated
                ],
                "decorated_count": len(decorated),
                "documented_released_count": len(released_doc),
                "documented_backlog_count": len(backlog_doc),
            },
        )

    return GateResult(
        status=GateStatus.PASS,
        gate_name="documented_routes",
        reason=(
            f"all {len(released_doc)} documented-released routes are decorated; "
            f"all {len(decorated)} decorated routes are either released or in v1.1 backlog "
            f"(backlog: {len(backlog_doc)})"
        ),
        evidence={
            "released_count": len(released_doc),
            "backlog_count": len(backlog_doc),
            "decorated_count": len(decorated),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="W31-N7: documented-route consistency gate."
    )
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    result = evaluate()
    if args.json:
        emit(result)  # exits

    if result.status is GateStatus.PASS:
        print(f"PASS (W31-N7): {result.reason}")
        return 0
    print(f"FAIL (W31-N7): {result.reason}")
    for rec in result.evidence.get("released_without_handler", []):
        print(
            f"  released-without-handler: {rec['method']} {rec['path']}"
        )
    for rec in result.evidence.get("undocumented_decorated", []):
        print(
            f"  decorated-but-undocumented: {rec['method']} {rec['path']}"
        )
    print(
        "\nFix: align §2 'Released routes' with the @router.<method>"
        " decorators or move undecorated routes to §13 v1.1 backlog."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
