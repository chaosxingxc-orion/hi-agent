#!/usr/bin/env python3
"""W14-D4: noqa and type: ignore discipline gate.

Every `noqa` and `type: ignore` comment MUST have an adjacent
`# expiry_wave: Wave N` comment on the same line OR the line immediately above.

Without expiry tracking, suppression comments silently accumulate and are never
cleaned up, masking real defects.

Additionally, expiry_wave values that are <= the current wave are treated as
expired and are flagged as failures (monotonic gate).

Exit 0: pass (all suppressions have future expiry).
Exit 1: fail (suppressions missing expiry_wave, or expiry_wave is expired).
Status values: pass | fail | not_applicable | deferred
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Import current_wave_number from the governance module.
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from _governance.wave import current_wave_number
    _CURRENT_WAVE = current_wave_number()
except Exception:
    _CURRENT_WAVE = 25  # fallback for standalone execution

_SUPPRESSION = re.compile(r"#\s*(?:noqa|type:\s*ignore)", re.IGNORECASE)
# Accept either form:
#   - comment-style: ``expiry_wave: Wave N`` (canonical)
#   - kwarg-style:   ``expiry_wave="Wave N"`` (used inside rule7-exempt
#                    annotations and other in-string contexts)
_EXPIRY = re.compile(
    r'expiry_wave\s*[:=\s]+["\']?Wave\s*(\d+)',
    re.IGNORECASE,
)

_SCAN_DIRS = ["hi_agent", "agent_kernel", "agent_server", "scripts", "tests"]
_EXEMPT_FILES = {
    pathlib.Path("hi_agent/artifacts/registry.py"),
    pathlib.Path("hi_agent/runtime/sync_bridge.py"),
    pathlib.Path("hi_agent/security/path_policy.py"),
    pathlib.Path("hi_agent/security/url_policy.py"),
    pathlib.Path("hi_agent/workflows/contracts.py"),
}


def _check_expiry(line: str, prev_line: str | None) -> str | None:
    """Return an issue string if the suppression is missing or has expired expiry_wave.

    Returns None if the annotation is present and not expired.
    """
    m = _EXPIRY.search(line)
    if not m and prev_line is not None:
        m = _EXPIRY.search(prev_line)
    if not m:
        return "missing_expiry"
    wave_num = int(m.group(1))
    if wave_num <= _CURRENT_WAVE:
        return f"expired_wave_{wave_num}_current_{_CURRENT_WAVE}"
    return None


def _scan_file(path: pathlib.Path) -> list[dict]:
    issues = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return issues

    for i, line in enumerate(lines, 1):
        if not _SUPPRESSION.search(line):
            continue
        prev_line = lines[i - 2] if i >= 2 else None
        issue_kind = _check_expiry(line, prev_line)
        if issue_kind is None:
            continue
        if issue_kind == "missing_expiry":
            issue_msg = "suppression missing expiry_wave comment"
        else:
            issue_msg = (
                f"suppression expiry_wave is expired ({issue_kind}); "
                "bump to Wave N+1 or fix the lint violation and remove"
            )
        issues.append(
            {
                "file": str(path.relative_to(ROOT)),
                "line": i,
                "content": line.strip()[:120],
                "issue": issue_msg,
            }
        )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="noqa/type:ignore discipline gate.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="Treat absent input as fail rather than not_applicable")
    args = parser.parse_args()

    all_issues: list[dict] = []
    for scan_dir in _SCAN_DIRS:
        d = ROOT / scan_dir
        if not d.exists():
            continue
        for py_file in sorted(d.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            rel = py_file.relative_to(ROOT)
            if rel in _EXEMPT_FILES:
                continue
            all_issues.extend(_scan_file(py_file))

    status = "pass" if not all_issues else "fail"
    result = {
        "status": status,
        "check": "noqa_discipline",
        "current_wave": _CURRENT_WAVE,
        "suppressions_without_expiry_or_expired": len(all_issues),
        "issues": all_issues[:50],
        "reason": (
            f"found {len(all_issues)} suppression(s) missing or with expired expiry_wave "
            f"(current wave: {_CURRENT_WAVE})"
        ) if all_issues else "",
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if all_issues:
            print(
                f"FAIL: {len(all_issues)} suppression(s) missing or expired expiry_wave "
                f"(current Wave {_CURRENT_WAVE})",
                file=sys.stderr,
            )
            for issue in all_issues[:20]:
                print(f"  {issue['file']}:{issue['line']}: {issue['issue']}", file=sys.stderr)
            if len(all_issues) > 20:
                print(f"  ... and {len(all_issues) - 20} more", file=sys.stderr)
        else:
            print(
                f"PASS: all noqa/type:ignore suppressions have future expiry_wave "
                f"(current Wave {_CURRENT_WAVE})"
            )

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
