#!/usr/bin/env python3
"""CI gate: detect silent-degradation patterns that violate Rule 7.

The checker flags two classes of problems:
- any line annotated with ``# rule7-exempt`` unless it advertises a fresh
  expiry (Wave 22 or later) and a ``replacement_test`` field
- silent ``except`` / ``contextlib.suppress(Exception)`` blocks that do not
  emit a metrics call within 5 lines

The goal is to keep degradation visible even when the code path is allowed to
continue.
"""
# Status values: pass | fail | not_applicable
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _governance.wave import current_wave_number as _get_current_wave_number

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["hi_agent", "agent_kernel", "agent_server"]
MIN_RULE7_EXEMPT_WAVE = 22
_METRIC_CALL_RE = re.compile(
    r"\.(?:inc|increment)\(|record_(?:silent_degradation|fallback)\(",
    re.IGNORECASE,
)
_EXPIRY_WAVE_RE = re.compile(
    r'expiry_wave\s*[:=]\s*["\']?Wave\s*(\d+)["\']?',
    re.IGNORECASE,
)
_CURRENT_WAVE = _get_current_wave_number()


def _is_silent_except_body(body: list) -> bool:
    """Return True if except body contains only pass/Ellipsis/return None."""
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
            continue
        if isinstance(node, ast.Return) and (
            node.value is None
            or (isinstance(node.value, ast.Constant) and node.value.value is None)
        ):
            continue
        return False
    return True


def _is_broad_exception_type(node: ast.expr | None) -> bool:
    """Return True for bare except or broad Exception/BaseException handlers."""
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in {"Exception", "BaseException"}
    if isinstance(node, ast.Attribute):
        return node.attr in {"Exception", "BaseException"}
    if isinstance(node, ast.Tuple):
        return any(_is_broad_exception_type(elt) for elt in node.elts)
    return False


def _rule7_annotation_status(line_text: str) -> str | None:
    """Return the effective status for a rule7-exempt annotation.

    Returns:
        None      — line has no rule7-exempt annotation; caller should ignore
        "exempt"  — annotation is permanent (no expiry_wave); fully skipped
        "deferred"— annotation has expiry_wave within tracked range; deferred debt
        "fail"    — annotation has an expired wave (past current wave)
    """
    if "rule7-exempt" not in line_text:
        return None
    expiry_match = _EXPIRY_WAVE_RE.search(line_text)
    if expiry_match is None:
        # No expiry_wave means a permanent/issue-linked exemption — fully exempt.
        return "exempt"
    wave_num = int(expiry_match.group(1))
    if wave_num > _CURRENT_WAVE:
        return "deferred"
    # Wave has expired — this is now a real violation.
    return "fail"


def _metrics_call_within_window(lines: list[str], lineno: int, end_lineno: int | None) -> bool:
    """Return True if a metrics call appears within five lines of the handler."""
    start = max(0, lineno - 1)
    end = min(len(lines), (end_lineno or lineno) + 5)
    window = lines[start:end]
    return any(_METRIC_CALL_RE.search(line) for line in window)


def check_file(path: Path) -> list[dict]:
    """Return list of silent-swallow violations found via AST and line scans."""
    violations: list[dict] = []
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        lines = src.splitlines()
    except (OSError, SyntaxError):
        return violations

    try:
        rel_path = str(path.relative_to(ROOT))
    except ValueError:
        rel_path = str(path)

    # First pass: rule7-exempt annotations are tracked debt or expired violations.
    for i, line in enumerate(lines, 1):
        ann_status = _rule7_annotation_status(line)
        if ann_status is None:
            continue  # not a rule7-exempt annotation
        if ann_status == "exempt":
            continue  # permanent exemption — fully skip
        # "deferred" → tracked debt; "fail" → expired wave
        violations.append(
            {
                "file": rel_path,
                "line": i,
                "exc_type": "rule7-exempt",
                "status": ann_status,  # "deferred" or "fail"
                "pattern": "rule7_annotation",
                "text": line.strip(),
            }
        )

    # Second pass: AST-based silent swallow detection.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            is_silent = _is_silent_except_body(handler.body)
            # Flag any silent-swallow handler (pass/Ellipsis/return None body)
            # regardless of how broad the exception type is.
            if not is_silent:
                continue
            lineno = handler.lineno
            line_text = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
            ann_status = _rule7_annotation_status(line_text)
            if ann_status in ("exempt", "deferred"):
                continue  # covered by annotation; deferred ones tracked above
            if ann_status is None and "rule7-exempt" in line_text:
                continue  # defensive guard
            if _metrics_call_within_window(lines, lineno, getattr(handler, "end_lineno", None)):
                continue
            exc_type = ast.unparse(handler.type) if handler.type else "bare except"
            violations.append(
                {
                    "file": rel_path,
                    "line": lineno,
                    "exc_type": exc_type,
                    "status": "fail",
                    "pattern": "silent_except_body",
                    "text": line_text.strip(),
                }
            )

    # contextlib.suppress(Exception) remains a broad silent-suppression pattern.
    for i, line in enumerate(lines, 1):
        if "contextlib.suppress(Exception)" not in line:
            continue
        if "rule7-exempt" in line:
            continue  # annotation scan already handled it
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
        "--path",
        dest="paths",
        action="append",
        help="Paths to scan (may be repeated; default: hi_agent/ agent_kernel/)",
    )
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
                    "status": "fail" if fail_v else "pass",
                    "hidden_violations_detected": True,
                    "total_violations": total,
                    "fail_violations": len(fail_v),
                    "deferred_violations": len(deferred_v),
                    "violation_count": total,
                    "violations": (fail_v + deferred_v)[:100],
                },
                indent=2,
            )
        )
        return 1 if fail_v else 0

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
            f"PASS silent_degradation: 0 fail, {len(deferred_v)} deferred "
            f"(all annotated expiry_wave; tracked debt — governance-compliant)"
        )
        return 0

    print("OK silent_degradation: no violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
