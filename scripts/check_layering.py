"""Layer violation checker 鈥?platform code must not import lower-stability layers.

Walks every .py file under hi_agent/ and agent_kernel/ and flags any import
whose module starts with ``examples``, ``tests``, ``scripts``, or ``docs``.

Allowlisted entries are lazy/deprecated shims explicitly tracked for removal.

Usage::

    python scripts/check_layering.py           # human-readable, exits non-zero on violation
    python scripts/check_layering.py --json    # machine-readable JSON report
"""

# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parent.parent

SOURCE_ROOTS = ("hi_agent", "agent_kernel")

SKIP_DIRS = frozenset({"venv", ".venv", "node_modules", ".git", "dist", "build", "__pycache__"})

# Lower-stability layer prefixes that platform code must not import from.
FORBIDDEN_PREFIXES = ("examples", "tests", "scripts", "docs")

# Allowlisted entries: lazy/deprecated shims scheduled for removal.
# Each entry: file path relative to REPO_ROOT, line number, reason, expiry wave.
ALLOWLIST: list[dict[str, object]] = [
    {
        "file": "hi_agent/artifacts/contracts.py",
        "line": 193,
        "reason": "lazy DeprecationWarning shim",
        "expiry_wave": "Wave 12",
    },
    {
        "file": "hi_agent/capability/bundles/__init__.py",
        "line": 32,
        "reason": "lazy DeprecationWarning shim for ResearchBundle (examples layer)",
        "expiry_wave": "Wave 12",
    },
]


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #


@dataclass
class Violation:
    file: str
    line: int
    module: str


@dataclass
class AllowlistHit:
    file: str
    line: int
    module: str
    reason: str
    expiry_wave: str


@dataclass
class LayeringReport:
    violations: list[Violation] = field(default_factory=list)
    allowlisted: list[AllowlistHit] = field(default_factory=list)
    head: str = ""

    @property
    def status(self) -> str:
        return "fail" if self.violations else "pass"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _get_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except OSError:
        return "unknown"


def _is_allowlisted(rel_path: str, lineno: int) -> dict[str, object] | None:
    norm = rel_path.replace("\\", "/")
    for entry in ALLOWLIST:
        if entry["file"] == norm and entry["line"] == lineno:
            return entry
    return None


def _extract_imports(tree: ast.Module) -> list[tuple[int, str]]:
    """Return (lineno, top_level_module) for every import in the AST."""
    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                results.append((node.lineno, top))
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            results.append((node.lineno, top))
    return results


def _check_dynamic_imports(tree: ast.Module) -> list[tuple[int, str]]:
    """Detect importlib.import_module('examples...') call sites."""
    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # importlib.import_module("examples....")
        is_import_module = (
            isinstance(func, ast.Attribute)
            and func.attr == "import_module"
        ) or (
            isinstance(func, ast.Name)
            and func.id == "import_module"
        )
        if not is_import_module:
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            module_str = str(node.args[0].value)
            top = module_str.split(".")[0]
            results.append((node.lineno, top))
    return results


def check_file(path: Path, report: LayeringReport) -> None:
    rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return

    candidates = _extract_imports(tree) + _check_dynamic_imports(tree)

    for lineno, top_module in candidates:
        if top_module not in FORBIDDEN_PREFIXES:
            continue
        allowlist_entry = _is_allowlisted(rel, lineno)
        if allowlist_entry is not None:
            # Reconstruct the actual module string for reporting
            # (best-effort: just use top_module, full module not stored here)
            report.allowlisted.append(
                AllowlistHit(
                    file=rel,
                    line=lineno,
                    module=top_module,
                    reason=str(allowlist_entry["reason"]),
                    expiry_wave=str(allowlist_entry["expiry_wave"]),
                )
            )
        else:
            report.violations.append(Violation(file=rel, line=lineno, module=top_module))


def run_check() -> LayeringReport:
    report = LayeringReport(head=_get_git_sha())
    for source_root in SOURCE_ROOTS:
        root_path = REPO_ROOT / source_root
        if not root_path.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                if filename.endswith(".py"):
                    check_file(Path(dirpath) / filename, report)
    return report


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def print_human(report: LayeringReport) -> None:
    if report.violations:
        print(f"FAIL 鈥?{len(report.violations)} layering violation(s) found:\n")
        for v in report.violations:
            print(f"  {v.file}:{v.line}  imports '{v.module}' (forbidden layer)")
        print()
    else:
        print("PASS 鈥?no layering violations found.")

    if report.allowlisted:
        print(f"Allowlisted ({len(report.allowlisted)}):")
        for a in report.allowlisted:
            print(f"  {a.file}:{a.line}  '{a.module}' 鈥?{a.reason} (expires {a.expiry_wave})")

    print(f"\nHEAD: {report.head}")


def print_json(report: LayeringReport) -> None:
    out = {
        "check": "layering",
        "status": report.status,
        "violations": [
            {"file": v.file, "line": v.line, "module": v.module}
            for v in report.violations
        ],
        "allowlisted": [
            {
                "file": a.file,
                "line": a.line,
                "module": a.module,
                "reason": a.reason,
                "expiry_wave": a.expiry_wave,
            }
            for a in report.allowlisted
        ],
        "head": report.head,
    }
    print(json.dumps(out, indent=2))


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    parser = argparse.ArgumentParser(description="Check platform layering violations.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON report instead of human-readable output.",
    )
    args = parser.parse_args()

    report = run_check()

    if args.json:
        print_json(report)
    else:
        print_human(report)

    sys.exit(0 if report.status == "pass" else 1)


if __name__ == "__main__":
    main()

