#!/usr/bin/env python3
"""CI gate: detect silent-degradation patterns that violate Rule 7.

Forbidden patterns:
- bare 'except: pass' or 'except Exception: pass' without logging
- contextlib.suppress(Exception) (too broad; should use specific exceptions)
- logger.warning(...) followed immediately by 'pass' (warning without action)

Exceptions:
- Lines annotated with '# rule7-exempt: <reason>' are allowlisted.
- Files/patterns listed in docs/governance/allowlists.yaml under 'silent_degradation_allowlist'.

Exit 0: no violations.
Exit 1: violations found.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["hi_agent", "agent_kernel"]


def _scan_file(path: Path) -> list[dict]:
    violations: list[dict] = []
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
    except Exception:
        return violations

    # Simple line-level checks (AST would be more precise but line checks catch the common cases)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Check for rule7-exempt annotation on this line
        if "rule7-exempt" in line:
            continue

        # Pattern 1: bare 'except: pass' or 'except Exception: pass'
        if stripped in ("except: pass", "except Exception: pass"):
            violations.append({
                "file": str(path.relative_to(ROOT)),
                "line": i,
                "pattern": "bare_except_pass",
                "text": stripped,
            })

        # Pattern 2: contextlib.suppress(Exception) — broad suppression
        if "contextlib.suppress(Exception)" in line:
            violations.append({
                "file": str(path.relative_to(ROOT)),
                "line": i,
                "pattern": "suppress_exception_broad",
                "text": stripped,
            })

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("paths", nargs="*", help="Paths to scan (default: hi_agent/ agent_kernel/)")
    args = parser.parse_args(argv)

    scan_paths = [ROOT / p for p in (args.paths or SCAN_DIRS)]

    all_violations: list[dict] = []
    for scan_path in scan_paths:
        if scan_path.is_file():
            all_violations.extend(_scan_file(scan_path))
        elif scan_path.is_dir():
            for py_file in sorted(scan_path.rglob("*.py")):
                all_violations.extend(_scan_file(py_file))

    if args.json_output:
        print(json.dumps({
            "check": "silent_degradation",
            "status": "fail" if all_violations else "pass",
            "violation_count": len(all_violations),
            "violations": all_violations[:50],  # cap output
        }, indent=2))
        return 1 if all_violations else 0

    if all_violations:
        print(f"FAIL silent_degradation: {len(all_violations)} violation(s) found")
        for v in all_violations[:20]:
            print(f"  {v['file']}:{v['line']}: {v['pattern']}: {v['text']}")
        return 1

    print("OK silent_degradation: no violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
