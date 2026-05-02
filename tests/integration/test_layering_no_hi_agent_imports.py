"""W31-N (N.4): AST-level layering test for agent_server route handlers.

Per R-AS-1, modules under ``agent_server/api/`` and
``agent_server/api/middleware/`` must NOT import from ``hi_agent.*``
under any condition — top-level OR function-body deferred imports.
The bootstrap module (``agent_server/bootstrap.py``) is the SINGLE
permitted seam.

This test walks the AST of every ``.py`` file under those two
directories and collects every ``Import`` and ``ImportFrom`` node
(including those nested inside function definitions). It fails if any
imported module starts with ``hi_agent``.

The test runs as part of the default pytest suite so a regression
introducing a deferred import lands as a hard CI failure rather than a
gate-script-only signal.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCAN_DIRS = (
    REPO_ROOT / "agent_server" / "api",
    REPO_ROOT / "agent_server" / "api" / "middleware",
)


def _collect_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Return ``(lineno, top_level_module_name)`` for every import node.

    Walks the entire AST (including ``FunctionDef`` and
    ``AsyncFunctionDef`` bodies) so deferred / function-body imports are
    NOT skipped.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                found.append((node.lineno, top))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top = module.split(".", 1)[0] if module else ""
            if top:
                found.append((node.lineno, top))
    return found


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for path in scan_dir.rglob("*.py"):
            # Skip __pycache__ and any test scaffolding the dirs may host.
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def test_no_hi_agent_imports_in_routes_or_middleware() -> None:
    """Fail if any agent_server/api/** module imports from hi_agent.*."""
    violations: list[tuple[str, int, str]] = []
    seen_files: list[Path] = []
    for path in _iter_python_files():
        seen_files.append(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for lineno, top in _collect_imports(tree):
            if top == "hi_agent":
                rel = path.relative_to(REPO_ROOT).as_posix()
                violations.append((rel, lineno, top))

    # Sanity: confirm we actually visited the directories. A typo in
    # SCAN_DIRS would otherwise let the test silently pass.
    assert seen_files, "no python files under agent_server/api/** to scan"

    assert not violations, (
        "R-AS-1 layering violation: agent_server/api/** imports from hi_agent.\n"
        + "\n".join(f"  {f}:{ln} imports '{m}'" for f, ln, m in violations)
    )
