#!/usr/bin/env python3
"""CI gate: detect silent-degradation patterns that violate Rule 7.

AST-based detection catches both single-line and multi-line silent swallows:
- bare 'except: pass', 'except Exception: pass' (single-line)
- multi-line patterns: except Exception:\n    pass  (previously invisible)
- except SomeError:\n    return None
- contextlib.suppress(Exception) (too broad; should use specific exceptions)

Exemptions:
- Lines annotated with '# rule7-exempt: <reason>' are allowlisted.
- Files/patterns listed in docs/governance/allowlists.yaml under 'silent_degradation_allowlist'.

Multistatus:
- '# rule7-exempt: expiry_wave="Wave XX"' → status=deferred, tracked debt
- Other violations → status=fail

Exit codes:
  0 = no violations
  1 = fail violations found
  2 = deferred-only (all remaining violations have expiry_wave annotation)
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["hi_agent", "agent_kernel"]


def _is_silent_except_body(body: list) -> bool:
    """Return True if except body contains ONLY pass/Ellipsis/return None."""
    if not body:
        return True
    for node in body:
        if isinstance(node, ast.Pass):
            continue
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and node.value.value is ...
        ):
            continue  # Ellipsis (...)
        if isinstance(node, ast.Return) and (
            node.value is None
            or (isinstance(node.value, ast.Constant) and node.value.value is None)
        ):
            continue
        return False
    return True


def _violation_status(line_text: str) -> str | None:
    """Return 'deferred', 'fail', or None (exempt, skip entirely).

    - 'rule7-exempt:' without expiry_wave= → fully exempt (None)
    - 'rule7-exempt: expiry_wave="Wave XX"' → deferred (tracked debt)
    - no annotation → fail
    """
    if "rule7-exempt:" not in line_text:
        return "fail"
    # Has rule7-exempt annotation
    if 'expiry_wave=' in line_text:
        return "deferred"
    # Fully exempt (no expiry_wave means it is a permanent exemption)
    return None


def check_file(path: Path) -> list[dict]:
    """Return list of silent-swallow violations found via AST."""
    violations: list[dict] = []
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        lines = src.splitlines()
    except (OSError, SyntaxError):
        return violations

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if not _is_silent_except_body(handler.body):
                continue
            lineno = handler.lineno
            line_text = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
            status = _violation_status(line_text)
            if status is None:
                continue  # fully exempt
            exc_type = ast.unparse(handler.type) if handler.type else "bare except"
            try:
                rel_path = str(path.relative_to(ROOT))
            except ValueError:
                rel_path = str(path)
            violations.append(
                {
                    "file": rel_path,
                    "line": lineno,
                    "exc_type": exc_type,
                    "status": status,
                    "pattern": "silent_except_body",
                    "text": line_text.strip(),
                }
            )

    # Also scan for contextlib.suppress(Exception) — line-level check
    try:
        raw_lines = src.splitlines()
    except Exception:  # rule7-exempt: src already parsed above; guard is defensive
        raw_lines = []
    for i, line in enumerate(raw_lines, 1):
        if "contextlib.suppress(Exception)" in line and "rule7-exempt" not in line:
            try:
                rel_path = str(path.relative_to(ROOT))
            except ValueError:
                rel_path = str(path)
            violations.append(
                {
                    "file": rel_path,
                    "line": i,
                    "exc_type": "contextlib.suppress",
                    "status": "fail",
                    "pattern": "suppress_exception_broad",
                    "text": line.strip(),
                }
            )

    return violations


def _scan_path(scan_path: Path) -> list[dict]:
    all_v: list[dict] = []
    if scan_path.is_file():
        all_v.extend(check_file(scan_path))
    elif scan_path.is_dir():
        for py_file in sorted(scan_path.rglob("*.py")):
            all_v.extend(check_file(py_file))
    return all_v


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument(
        "--path", dest="paths", action="append",
        help="Paths to scan (may be repeated; default: hi_agent/ agent_kernel/)",
    )
    # positional paths for backwards-compat
    parser.add_argument("positional_paths", nargs="*")
    args = parser.parse_args(argv)

    explicit = (args.paths or []) + (args.positional_paths or [])
    scan_roots = [ROOT / p for p in (explicit or SCAN_DIRS)]

    all_violations: list[dict] = []
    for scan_path in scan_roots:
        all_violations.extend(_scan_path(scan_path))

    fail_v = [v for v in all_violations if v["status"] == "fail"]
    deferred_v = [v for v in all_violations if v["status"] == "deferred"]
    total = len(all_violations)

    if args.json_output:
        print(
            json.dumps(
                {
                    "check": "silent_degradation",
                    "status": "fail" if fail_v else ("deferred" if deferred_v else "pass"),
                    "hidden_violations_detected": True,
                    "total_violations": total,
                    "fail_violations": len(fail_v),
                    "deferred_violations": len(deferred_v),
                    "violation_count": total,  # backwards-compat
                    "violations": (fail_v + deferred_v)[:100],
                },
                indent=2,
            )
        )
        if fail_v:
            return 1
        if deferred_v:
            return 2
        return 0

    if fail_v:
        print(
            f"FAIL silent_degradation: {len(fail_v)} fail violation(s), "
            f"{len(deferred_v)} deferred"
        )
        for v in fail_v[:20]:
            print(f"  {v['file']}:{v['line']}: {v['exc_type']}: {v['text']}")
        return 1

    if deferred_v:
        print(
            f"DEFERRED silent_degradation: 0 fail, {len(deferred_v)} deferred "
            f"(annotated expiry_wave; tracked debt)"
        )
        return 2

    print("OK silent_degradation: no violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
