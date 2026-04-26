#!/usr/bin/env python3
"""Check for expired time-bounded waivers (comments, shims, TODOs)."""
from __future__ import annotations
import argparse
import pathlib
import re
import subprocess
import sys
import json

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _current_wave import current_wave, wave_number, is_expired  # noqa: E402

_WAIVER_PATTERN = re.compile(
    r"(Wave\s+\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_REMOVAL_VERBS = re.compile(
    r"\b(removed? in|remove by|until Wave|before Wave|deprecated.*Wave|by Wave)\b",
    re.IGNORECASE,
)

_SCAN_ROOTS = ["hi_agent", "agent_kernel", "scripts"]


def scan_file(path: pathlib.Path) -> list[dict]:
    violations = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for i, line in enumerate(text.splitlines(), 1):
        if _REMOVAL_VERBS.search(line):
            waves = _WAIVER_PATTERN.findall(line)
            for w in waves:
                if is_expired(w):
                    violations.append({
                        "file": str(path),
                        "line": i,
                        "wave": w,
                        "text": line.strip()[:120],
                    })
    return violations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = pathlib.Path(__file__).parent.parent
    violations = []
    for scan_root in _SCAN_ROOTS:
        scan_path = root / scan_root
        if scan_path.exists():
            for path in scan_path.rglob("*.py"):
                violations.extend(scan_file(path))

    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, cwd=root
    ).stdout.strip()

    status = "fail" if violations else "pass"

    if args.json:
        print(json.dumps({
            "check": "expired_waivers",
            "status": status,
            "current_wave": current_wave(),
            "violations": violations,
            "head": sha,
        }))
    else:
        if violations:
            for v in violations:
                print(f"EXPIRED [{v['wave']}] {v['file']}:{v['line']}: {v['text']}")
            sys.exit(1)
        else:
            print(f"OK: no expired waivers found (current wave: {current_wave()})")

if __name__ == "__main__":
    main()
