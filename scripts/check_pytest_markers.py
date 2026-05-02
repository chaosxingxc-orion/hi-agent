#!/usr/bin/env python3
"""CI gate: pytest marker discipline — every custom marker must be registered (AX-D D4).

Scans tests/ for @pytest.mark.X usage and verifies each custom marker
is declared in pyproject.toml [tool.pytest.ini_options] markers list.

Skips markers that are: pytest built-ins, explicitly allowlisted as standard,
or already registered in pyproject.toml.

Exit 0: PASS
Exit 1: FAIL (unregistered markers found)
Exit 2: not_applicable (tests dir or config absent, non-strict mode)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]  # expiry_wave: permanent
    except ImportError:
        tomllib = None  # type: ignore[assignment]  # expiry_wave: permanent

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
PYPROJECT = ROOT / "pyproject.toml"

# Standard pytest built-in and widely-used plugin markers — never flagged.
_BUILTIN_MARKERS: frozenset[str] = frozenset({
    "skip",
    "skipif",
    "xfail",
    "parametrize",
    "usefixtures",
    "filterwarnings",
    # pytest-asyncio
    "asyncio",
    # pytest-anyio
    "anyio",
    # pytest-timeout
    "timeout",
})

_MARK_PATTERN = re.compile(r"@pytest\.mark\.(\w+)")


def _load_registered_markers() -> set[str]:
    """Read [tool.pytest.ini_options] markers from pyproject.toml."""
    if tomllib is None:
        # Fall back to simple regex scan when tomllib is unavailable.
        if not PYPROJECT.exists():
            return set()
        text = PYPROJECT.read_text(encoding="utf-8", errors="replace")
        registered: set[str] = set()
        in_markers = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("markers") and "=" in stripped:
                in_markers = True
            if in_markers:
                m = re.search(r'["\'](\w+)\s*:', line)
                if m:
                    registered.add(m.group(1))
                if stripped.startswith("]"):
                    break
        return registered

    if not PYPROJECT.exists():
        return set()
    try:
        with open(PYPROJECT, "rb") as fh:
            config = tomllib.load(fh)
        markers_list: list[str] = (
            config.get("tool", {})
            .get("pytest", {})
            .get("ini_options", {})
            .get("markers", [])
        )
        registered = set()
        for entry in markers_list:
            # Each entry is like "slow: mark test as slow" — take the part before ':'
            name = entry.split(":")[0].strip()
            if name:
                registered.add(name)
        return registered
    except Exception:
        return set()


def _scan_test_markers(registered: set[str]) -> dict[str, list[str]]:
    """Return mapping of unregistered marker name -> list of 'relpath:line' locations."""
    unregistered: dict[str, list[str]] = {}
    allowed = _BUILTIN_MARKERS | registered

    for py_file in sorted(TESTS_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for marker_name in _MARK_PATTERN.findall(line):
                if marker_name in allowed:
                    continue
                loc = f"{py_file.relative_to(ROOT)}:{lineno}"
                unregistered.setdefault(marker_name, []).append(loc)

    return unregistered


def main() -> int:
    parser = argparse.ArgumentParser(description="Pytest marker discipline gate (AX-D D4).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat absent tests dir or missing config as FAIL",
    )
    args = parser.parse_args()

    if not TESTS_DIR.exists():
        msg: dict = {
            "status": "fail" if args.strict else "not_applicable",
            "check": "pytest_markers",
            "reason": f"tests dir absent: {TESTS_DIR}",
        }
        if args.json:
            print(json.dumps(msg, indent=2))
        else:
            prefix = "FAIL (strict)" if args.strict else "not_applicable"
            out = sys.stderr if args.strict else sys.stdout
            print(f"{prefix}: tests dir absent", file=out)
        return 1 if args.strict else 2

    registered = _load_registered_markers()

    if not registered and not PYPROJECT.exists():
        msg = {
            "status": "fail" if args.strict else "not_applicable",
            "check": "pytest_markers",
            "reason": "pyproject.toml absent — cannot load registered markers",
        }
        if args.json:
            print(json.dumps(msg, indent=2))
        else:
            prefix = "FAIL (strict)" if args.strict else "not_applicable"
            out = sys.stderr if args.strict else sys.stdout
            print(f"{prefix}: pyproject.toml absent", file=out)
        return 1 if args.strict else 2

    unregistered = _scan_test_markers(registered)

    status = "fail" if unregistered else "pass"
    result: dict = {
        "status": status,
        "check": "pytest_markers",
        "registered_count": len(registered),
        "unregistered_markers": {k: v for k, v in unregistered.items()},  # noqa: C416  # expiry_wave: permanent  # added: W25 baseline sweep
        "reason": f"{len(unregistered)} unregistered marker(s)" if unregistered else "",
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if unregistered:
            print(
                f"FAIL: {len(unregistered)} unregistered pytest marker(s):",
                file=sys.stderr,
            )
            for name, locs in list(unregistered.items())[:10]:
                print(f"  @pytest.mark.{name} — first at {locs[0]}", file=sys.stderr)
            if len(unregistered) > 10:
                print(f"  ... and {len(unregistered) - 10} more", file=sys.stderr)
        else:
            print(
                f"PASS: all pytest markers registered "
                f"({len(registered)} registered markers)"
            )

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
