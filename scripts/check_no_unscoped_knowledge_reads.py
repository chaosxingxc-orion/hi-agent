#!/usr/bin/env python3
"""CI gate: every public ``KnowledgeWiki`` read site MUST pass ``tenant_id``.

W34-F.4 (B-W34-3): the wiki layer partitions per tenant. A call like
``wiki.get_page("page-id")`` without a ``tenant_id`` keyword argument is
a tenant-scoping defect — under research/prod posture the wiki layer
will raise ``ValueError`` at runtime, but the gate catches it earlier so
new code cannot regress the partition contract.

Scope:
- Walks every ``*.py`` under ``hi_agent/`` and ``agent_server/``.
- For each ``Call`` whose ``func`` is an ``Attribute`` named one of
  ``get_page`` / ``list_pages`` / ``search`` / ``update_page`` /
  ``remove_page`` / ``get_linked_pages`` / ``rebuild_index`` /
  ``to_context_string`` and whose receiver looks like a
  ``KnowledgeWiki`` (variable named ``wiki`` / ``self._wiki`` / ``km.wiki``),
  the call MUST contain a ``tenant_id=`` keyword argument.
- ``add_page`` is exempt because it consumes ``page.tenant_id`` from the
  dataclass — the gate verifies the caller constructs the page with
  ``tenant_id=`` instead, which the contract-spine gate already enforces.

Allowlist:
- ``hi_agent/knowledge/wiki.py`` (the implementation itself).
- All files under ``tests/``.
- Files where the call is preceded on the same line or the line above by
  a ``# scope: process-internal`` rationale comment.

Exit 0 on PASS, 1 on FAIL. JSON multistatus emitted on ``--json``.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Methods that read or mutate per-tenant state and therefore require a
# ``tenant_id=`` kwarg at every call site (W34-F.4).
SCOPED_METHODS = {
    "get_page",
    "list_pages",
    "search",
    "update_page",
    "remove_page",
    "get_linked_pages",
    "rebuild_index",
    "to_context_string",
    "lint",
}

# Receiver name patterns that indicate the call target is a
# ``KnowledgeWiki`` instance.
WIKI_RECEIVER_HINTS = {
    "wiki",
    "_wiki",
    "self._wiki",
    "km.wiki",
    "self.knowledge_manager.wiki",
}

# File-path allowlist (relative to repo root, forward slashes).
ALLOWLIST = {
    "hi_agent/knowledge/wiki.py",
}


def _receiver_label(node: ast.AST) -> str:
    """Render a receiver expression as a readable dotted name for matching."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _receiver_label(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _receiver_label(node.func)
    return ""


def _looks_like_wiki(receiver_label: str) -> bool:
    """Heuristic: does the receiver look like a KnowledgeWiki instance?"""
    if not receiver_label:
        return False
    # Match exact names and dotted suffixes.
    short = receiver_label.split(".")[-1]
    if short in {"wiki", "_wiki"}:
        return True
    if receiver_label in WIKI_RECEIVER_HINTS:
        return True
    # Common pattern: ``something.wiki.get_page(...)`` or
    # ``something._wiki.get_page(...)`` — receiver is dotted ending in
    # `wiki` or `_wiki`.
    return short.endswith("wiki") or short.endswith("_wiki")


def _has_tenant_id_kwarg(call: ast.Call) -> bool:
    """Return True iff the call passes a ``tenant_id=`` keyword argument."""
    return any(kw.arg == "tenant_id" for kw in call.keywords)


def _scan_file(path: Path) -> list[dict[str, object]]:
    """Return a list of finding dicts for the given file."""
    findings: list[dict[str, object]] = []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return findings

    source_lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in SCOPED_METHODS:
            continue
        receiver = _receiver_label(func.value)
        if not _looks_like_wiki(receiver):
            continue
        if _has_tenant_id_kwarg(node):
            continue

        # Per-line rationale escape hatch.
        line_idx = node.lineno - 1
        if 0 <= line_idx < len(source_lines):
            current = source_lines[line_idx]
            previous = source_lines[line_idx - 1] if line_idx > 0 else ""
            if (
                "# scope: process-internal" in current
                or "# scope: process-internal" in previous
            ):
                continue

        findings.append(
            {
                "file": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "line": node.lineno,
                "col": node.col_offset,
                "method": func.attr,
                "receiver": receiver,
                "message": (
                    f"{func.attr}({receiver}.{func.attr}) called without "
                    "tenant_id= keyword argument (W34-F.4 / B-W34-3)."  # wave-literal-ok
                ),
            }
        )
    return findings


def _iter_scan_paths() -> list[Path]:
    paths: list[Path] = []
    for sub in ("hi_agent", "agent_server"):
        root = REPO_ROOT / sub
        if not root.exists():
            continue
        paths.extend(root.rglob("*.py"))
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args()

    findings: list[dict[str, object]] = []
    files_scanned = 0
    for path in _iter_scan_paths():
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if rel in ALLOWLIST:
            continue
        # Skip tests directory if it ever lands under hi_agent/.
        if "/tests/" in rel:
            continue
        files_scanned += 1
        findings.extend(_scan_file(path))

    if args.json:
        payload = {
            "gate": "no_unscoped_knowledge_reads",
            "files_scanned": files_scanned,
            "findings": findings,
            "status": "PASS" if not findings else "FAIL",
        }
        print(json.dumps(payload, indent=2))
    else:
        if findings:
            print(
                f"FAIL: {len(findings)} unscoped KnowledgeWiki read site(s) "
                f"({files_scanned} files scanned).",
                file=sys.stderr,
            )
            for f in findings:
                print(
                    f"  {f['file']}:{f['line']}:{f['col']}  {f['message']}",
                    file=sys.stderr,
                )
        else:
            print(
                f"PASS: no unscoped KnowledgeWiki read sites "
                f"({files_scanned} files scanned)."
            )
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
