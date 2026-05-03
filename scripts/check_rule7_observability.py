#!/usr/bin/env python3
""" governance gate: enforce Rule 7 closure across hi_agent/llm/ and hi_agent/runtime/.

Scans all Python files under ``hi_agent/llm/`` and ``hi_agent/runtime/`` for
two prohibited markers:

* ``# rule7-exempt`` — a swallow annotation that bypasses Rule 7 alarm-bell
  requirements without proper four-pillar observability.
* ``Rule 7 violation`` — an explicit admission of an unfixed Rule 7 defect
  in a log message or comment.

Both markers indicate that a fallback path does not satisfy the four Rule 7
pillars (Countable / Attributable / Inspectable / Gate-asserted) and must be
replaced with proper observability before the affected file can ship.

Expiry-annotated exemptions of the form ``# rule7-exempt: expiry_wave="Wave N"``
are permitted if Wave N is in the future relative to the current wave recorded
in ``docs/current-wave.txt``.  Expired exemptions fail the gate.

Outputs multistatus JSON via ``scripts/_governance/multistatus.py`` so
this gate plays well with the multistatus runner.
"""
# Status values: pass | fail | not_applicable
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts._governance.multistatus import emit_and_exit

# Directories to scan (relative to repo root).
_SCAN_ROOTS = [
    _REPO_ROOT / "hi_agent" / "llm",
    _REPO_ROOT / "hi_agent" / "runtime",
]

_RULE7_VIOLATION_LITERAL = "Rule 7 violation"
_RULE7_EXEMPT_LITERAL = "rule7-exempt"

# Matches ``# rule7-exempt: expiry_wave="Wave N"`` to extract wave number.
_EXPIRY_RE = re.compile(r'rule7-exempt[^"\']*["\']?[Ww]ave\s+(\d+)["\']?')
# W30: matches ``# rule7-exempt: expiry_wave="permanent"`` (or with ``:`` form)
# Permanent declarations are accepted closure per Rule 17 (tracked technical
# debt, not a closure to bump). The annotation MUST appear next to a brief
# justification; this gate doesn't validate the justification text.
_PERMANENT_RE = re.compile(
    r'rule7-exempt[^"\']*expiry_wave\s*[:=]\s*["\']?permanent["\']?',
    re.IGNORECASE,
)

_CURRENT_WAVE_PATH = _REPO_ROOT / "docs" / "current-wave.txt"


def _current_wave() -> int | None:
    """Return the current wave number from current-wave.txt, or None if unreadable."""
    try:
        text = _CURRENT_WAVE_PATH.read_text(encoding="utf-8").strip()
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else None
    except OSError:
        return None


def _iter_py_files(roots: list[Path]) -> list[Path]:
    """Yield all .py files under the given roots, skipping __pycache__."""
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def _scan_file(path: Path, current_wave_num: int | None) -> list[dict[str, object]]:
    """Return violation dicts for a single file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    violations: list[dict[str, object]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        # Check for "Rule 7 violation" literal in any context.
        if _RULE7_VIOLATION_LITERAL in line:
            violations.append(
                {
                    "marker": _RULE7_VIOLATION_LITERAL,
                    "file": str(path.relative_to(_REPO_ROOT)),
                    "line": idx,
                    "snippet": line.rstrip(),
                }
            )
            continue

        # Check for rule7-exempt annotation.
        if _RULE7_EXEMPT_LITERAL not in line:
            continue

        # W30: permanent declarations are valid closure (Rule 17 tracked debt).
        if _PERMANENT_RE.search(line):
            continue

        # Allow if expiry_wave is in the future.
        m = _EXPIRY_RE.search(line)
        if m and current_wave_num is not None:
            expiry = int(m.group(1))
            if expiry > current_wave_num:
                # Valid future exemption — skip.
                continue

        # Expired or bare rule7-exempt.
        violations.append(
            {
                "marker": _RULE7_EXEMPT_LITERAL,
                "file": str(path.relative_to(_REPO_ROOT)),
                "line": idx,
                "snippet": line.rstrip(),
            }
        )

    return violations


def main() -> None:
    """Run main."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="emit multistatus JSON to stdout",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat not_applicable as fail",
    )
    args = parser.parse_args()

    existing_roots = [r for r in _SCAN_ROOTS if r.is_dir()]
    if not existing_roots:
        emit_and_exit(
            status="not_applicable",
            check="check_rule7_observability",
            json_output=args.json_output,
            strict=args.strict,
            reason="None of the scan roots exist: " + ", ".join(str(r) for r in _SCAN_ROOTS),
        )

    current_wave_num = _current_wave()
    files = _iter_py_files(existing_roots)

    all_violations: list[dict[str, object]] = []
    for path in files:
        all_violations.extend(_scan_file(path, current_wave_num))

    scanned_count = len(files)

    if all_violations:
        emit_and_exit(
            status="fail",
            check="check_rule7_observability",
            json_output=args.json_output,
            strict=args.strict,
            reason=(
                f"{len(all_violations)} Rule 7 marker(s) found across "
                f"{scanned_count} file(s) in hi_agent/llm/ + hi_agent/runtime/: "
                + ", ".join(
                    f"{v['file']}:{v['line']} ({v['marker']})" for v in all_violations
                )
            ),
            violations=all_violations,
            scanned_files=scanned_count,
        )

    emit_and_exit(
        status="pass",
        check="check_rule7_observability",
        json_output=args.json_output,
        strict=args.strict,
        message=(
            f"No Rule 7 markers found across {scanned_count} file(s) "
            "in hi_agent/llm/ + hi_agent/runtime/."
        ),
        scanned_files=scanned_count,
    )


if __name__ == "__main__":
    main()
