"""Layer violation checker — platform code must not import lower-stability layers.

W31-N (N.5) extends the original ``hi_agent`` / ``agent_kernel`` scan to
also cover ``agent_server/api`` and ``agent_server/api/middleware`` per
R-AS-1: those route-handler modules must NOT import from ``hi_agent.*``
under any circumstance, including function-body deferred imports.

Walks every .py file under each scan root and flags any import whose
top-level module is in the corresponding forbidden-prefix set. Imports
nested inside function/method definitions are also captured.

Allowlisted entries are lazy/deprecated shims explicitly tracked for
removal.

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

SKIP_DIRS = frozenset({"venv", ".venv", "node_modules", ".git", "dist", "build", "__pycache__"})

# Per-scan-root rule definitions:
#   * ``forbidden`` — top-level module names that may not appear in any import
#   * ``allowlist`` — bool indicating whether ALLOWLIST entries are honored
#                     (False means no exception is permitted regardless of the
#                     central ALLOWLIST)
#
# W31-N3 adds ``agent_server/api`` (nested ``middleware`` is covered by
# the os.walk recursion) with FORBIDDEN_PREFIXES = ("hi_agent",) and
# allowlist disabled — there is no permitted "deferred" import escape
# valve under R-AS-1.
SOURCE_ROOTS_CONFIG: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("hi_agent", ("examples", "tests", "scripts", "docs"), True),
    ("agent_kernel", ("examples", "tests", "scripts", "docs"), True),
    ("agent_server/api", ("hi_agent",), False),
)

# Backward compatibility: callers that introspect SOURCE_ROOTS or
# FORBIDDEN_PREFIXES at module import time keep working with the
# original two-root configuration.
SOURCE_ROOTS = tuple(root for root, _, _ in SOURCE_ROOTS_CONFIG[:2])
FORBIDDEN_PREFIXES = SOURCE_ROOTS_CONFIG[0][1]

# Allowlisted entries: lazy/deprecated shims scheduled for removal.
# Each entry: file path relative to REPO_ROOT, line number, reason, expiry wave.
ALLOWLIST: list[dict[str, object]] = [
    {
        "file": "hi_agent/artifacts/contracts.py",
        "line": 193,
        "reason": "lazy DeprecationWarning shim",
        "expiry_wave": "Wave 30",
    },
    {
        "file": "hi_agent/capability/bundles/__init__.py",
        "line": 32,
        "reason": "lazy DeprecationWarning shim for ResearchBundle (examples layer)",
        "expiry_wave": "Wave 30",
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


def check_file(
    path: Path,
    report: LayeringReport,
    *,
    forbidden_prefixes: tuple[str, ...] = FORBIDDEN_PREFIXES,
    allowlist_enabled: bool = True,
) -> None:
    """Scan a single file under the given forbidden-prefix rule.

    W31-N (N.5): when ``allowlist_enabled`` is False every match is a
    violation, regardless of whether the central ALLOWLIST contains the
    file:line. This is the ``agent_server/api/**`` rule per R-AS-1.
    """
    rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return

    candidates = _extract_imports(tree) + _check_dynamic_imports(tree)

    for lineno, top_module in candidates:
        if top_module not in forbidden_prefixes:
            continue
        allowlist_entry = _is_allowlisted(rel, lineno) if allowlist_enabled else None
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
    """Scan every source root with its associated forbidden-prefix rule."""
    report = LayeringReport(head=_get_git_sha())
    for source_root, forbidden, allow_enabled in SOURCE_ROOTS_CONFIG:
        root_path = REPO_ROOT / source_root
        if not root_path.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                check_file(
                    Path(dirpath) / filename,
                    report,
                    forbidden_prefixes=forbidden,
                    allowlist_enabled=allow_enabled,
                )
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

