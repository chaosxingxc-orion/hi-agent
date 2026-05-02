#!/usr/bin/env python3
"""CI gate: hi_agent/ source must not contain research-domain vocabulary in identifiers.

Checks identifier names (not string values) that embed research-domain terms.
Allowlist entries carry # legacy: annotations in source.
Shim files are allowlisted by path.

Exit codes:
  0 鈥?pass (or warn-only soft-ban hits)
  1 鈥?fail (hard-ban hits, or migration-guide violations)

Flags:
  --json  Emit structured JSON report instead of human-readable output.
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
HI_AGENT = ROOT / "hi_agent"
MIGRATION_GUIDES = ROOT / "docs" / "migration-guides"

# Files that are the shim/compat layer 鈥?allowed to reference old names
# (W18: all entries removed; shims burned down)
_PATH_ALLOWLIST: set[str] = set()

# Hard-ban: any match in non-allowlisted hi_agent/ code fails immediately.
# These are deprecated / removed names; a shim exists for each.
_HARD_BAN_IDENTIFIERS = frozenset({
    "pi_run_id",                  # legacy field 鈥?use lead_run_id
    "RunPostmortem",              # use RunRetrospective
    "ProjectPostmortem",          # use ProjectRetrospective
    "EvolutionExperiment",        # use EvolutionTrial
})

# Soft-ban: research-domain vocabulary targeted for removal in Wave 12.
# Reported as WARN; do not fail unless the file is outside the soft-ban allowlist.
_SOFT_BAN_IDENTIFIERS = frozenset({
    "paper",
    "citation",
    "lean_proof",
    "peer_review",
    "survey_synthesis",
    "survey_fetch",
    "pi_agent",
    "literature",
    "CitationValidator",
    "CitationArtifact",
    "PaperArtifact",
    "LeanProofArtifact",
    "apply_research_defaults",   # deleted in Wave 18 (C4); flag any surviving callsites
})

# Files allowed to contain soft-ban identifiers (Wave 12 migration targets).
# These carry active but Wave-12-targeted usage; flag them as WARN only.
# (W18: all entries removed)
_SOFT_BAN_PATH_ALLOWLIST: set[str] = set()

_LEGACY_ANNOTATION = "# legacy:"

# Text that must not appear in migration guide markdown files.
_MIGRATION_GUIDE_FORBIDDEN_TEXT = "from examples.research_overlay"


def _rel(path: Path) -> str:
    """Return a repo-relative string, or the absolute path for out-of-tree files."""
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _is_allowlisted(path: Path) -> bool:
    return _rel(path) in _PATH_ALLOWLIST


def _is_soft_ban_allowlisted(path: Path) -> bool:
    return _rel(path) in _SOFT_BAN_PATH_ALLOWLIST


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def check_file(path: Path) -> list[str]:
    """Return hard-ban violation messages for a single Python file.

    Kept for backward compatibility with existing tests.
    """
    hard, _soft = check_file_split(path)
    return hard


def check_file_split(
    path: Path,
) -> tuple[list[str], list[str]]:
    """Return (hard_violations, soft_violations) for a single Python file.

    Each entry is a human-readable string suitable for console output.
    """
    if _is_allowlisted(path):
        return [], []

    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return [], []

    lines = src.splitlines()
    hard: list[str] = []
    soft: list[str] = []
    label = _rel(path)
    soft_allowed = _is_soft_ban_allowlisted(path)

    def _line_text(lineno: int) -> str:
        return lines[lineno - 1] if 0 < lineno <= len(lines) else ""

    def _report_hard(lineno: int, identifier: str, reason: str) -> None:
        hard.append(f"  {label}:{lineno}: {identifier} 鈥?{reason}")

    def _report_soft(lineno: int, identifier: str) -> None:
        if not soft_allowed:
            soft.append(
                f"  {label}:{lineno}: {identifier} 鈥?soft-ban (expiry Wave 12)"
            )

    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", 0)
        line_text = _line_text(lineno)
        if _LEGACY_ANNOTATION in line_text:
            continue

        # 鈹€鈹€ existing checks 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€  # noqa: E501  # expiry_wave: Wave 30  # added: W25 baseline sweep
        if isinstance(node, ast.Attribute):
            if node.attr in _HARD_BAN_IDENTIFIERS:
                _report_hard(lineno, f".{node.attr}", "research vocab (hard-ban)")
            elif node.attr in _SOFT_BAN_IDENTIFIERS:
                _report_soft(lineno, f".{node.attr}")

        if isinstance(node, ast.keyword):
            if node.arg in _HARD_BAN_IDENTIFIERS:
                _report_hard(lineno, f"{node.arg}=", "kwarg 鈥?research vocab (hard-ban)")
            elif node.arg in _SOFT_BAN_IDENTIFIERS:
                _report_soft(lineno, f"{node.arg}=")

        if isinstance(node, ast.Call):
            func = node.func
            cls_name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if cls_name in _HARD_BAN_IDENTIFIERS:
                _report_hard(lineno, f"{cls_name}()", "use renamed class (hard-ban)")
            elif cls_name in _SOFT_BAN_IDENTIFIERS:
                _report_soft(lineno, f"{cls_name}()")

        # 鈹€鈹€ new checks 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€  # noqa: E501  # expiry_wave: Wave 30  # added: W25 baseline sweep

        # FunctionDef.name / AsyncFunctionDef.name
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in _HARD_BAN_IDENTIFIERS:
                _report_hard(lineno, f"def {node.name}", "function name 鈥?research vocab")
            elif node.name in _SOFT_BAN_IDENTIFIERS:
                _report_soft(lineno, f"def {node.name}")

        # ClassDef.name
        if isinstance(node, ast.ClassDef):
            if node.name in _HARD_BAN_IDENTIFIERS:
                _report_hard(lineno, f"class {node.name}", "class name 鈥?research vocab (hard-ban)")  # noqa: E501  # expiry_wave: Wave 30  # added: W25 baseline sweep
            elif node.name in _SOFT_BAN_IDENTIFIERS:
                _report_soft(lineno, f"class {node.name}")

        # ImportFrom.names 鈥?each alias
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                # check both the imported name and the local alias
                for candidate in (alias.name, alias.asname):
                    if candidate is None:
                        continue
                    if candidate in _HARD_BAN_IDENTIFIERS:
                        _report_hard(lineno, candidate, "import name 鈥?research vocab (hard-ban)")
                    elif candidate in _SOFT_BAN_IDENTIFIERS:
                        _report_soft(lineno, candidate)

        # Top-level Name assignments: x = ...  where x is a banned identifier
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name = node.targets[0].id
            if name in _HARD_BAN_IDENTIFIERS:
                _report_hard(lineno, name, "assignment target 鈥?research vocab (hard-ban)")
            elif name in _SOFT_BAN_IDENTIFIERS:
                _report_soft(lineno, name)

    return hard, soft


def _check_migration_guides() -> list[dict]:
    """Scan docs/migration-guides/*.md for forbidden import recommendations.

    Returns a list of violation dicts with keys: file, line, text.
    """
    violations: list[dict] = []
    if not MIGRATION_GUIDES.is_dir():
        return violations
    for md_file in MIGRATION_GUIDES.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(content.splitlines(), start=1):
            if _MIGRATION_GUIDE_FORBIDDEN_TEXT in line:
                violations.append(
                    {
                        "file": _rel(md_file),
                        "line": lineno,
                        "text": line.strip(),
                    }
                )
    return violations


def _build_structured_violations(
    hard_messages: list[str],
    soft_messages: list[str],
    migration_violations: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Convert human-readable messages to structured dicts for --json output."""

    def _parse_message(msg: str) -> dict:
        # Format: "  label:lineno: identifier 鈥?reason"
        msg = msg.strip()
        parts = msg.split(":", 2)
        file_part = parts[0].strip() if len(parts) > 0 else ""
        line_part = parts[1].strip() if len(parts) > 1 else "0"
        rest = parts[2].strip() if len(parts) > 2 else msg
        identifier, _, reason = rest.partition(" 鈥?")
        return {
            "file": file_part,
            "line": int(line_part) if line_part.isdigit() else 0,
            "identifier": identifier.strip(),
            "reason": reason.strip(),
        }

    def _parse_soft_message(msg: str) -> dict:
        d = _parse_message(msg)
        d["expiry_wave"] = "Wave 12"  # wave-literal-ok: historical allowlist expiry
        d.pop("reason", None)
        return d

    hard_structs = [_parse_message(m) for m in hard_messages]
    soft_structs = [_parse_soft_message(m) for m in soft_messages]
    return hard_structs, soft_structs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check hi_agent/ for research-domain vocabulary."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit structured JSON report.",
    )
    parser.add_argument(
        "--expiry-wave",
        dest="expiry_wave",
        default=None,
        help=(
            "When provided and soft-ban vocab is found, emit status 'deferred' (exit 3) "
            "instead of 'warn'. Example: --expiry-wave 'Wave 22'"
        ),
    )
    args = parser.parse_args(argv)

    all_hard: list[str] = []
    all_soft: list[str] = []

    for py_file in HI_AGENT.rglob("*.py"):
        hard, soft = check_file_split(py_file)
        all_hard.extend(hard)
        all_soft.extend(soft)

    migration_violations = _check_migration_guides()

    if args.json_output:
        hard_structs, soft_structs = _build_structured_violations(
            all_hard, all_soft, migration_violations
        )
        if all_hard or migration_violations:
            status = "fail"
        elif all_soft:
            # With --expiry-wave: emit "deferred" (exit 3); without it: emit "warn" (exit 1)
            status = "deferred" if args.expiry_wave else "warn"
        else:
            status = "pass"
        report: dict = {
            "check": "no_research_vocab",
            "status": status,
            "violations": hard_structs + migration_violations,
            "hard_violations": hard_structs,
            "soft_violations": soft_structs,
            "migration_guide_violations": migration_violations,
            "head": _git_head(),
        }
        if args.expiry_wave and status == "deferred":
            report["expiry_wave"] = args.expiry_wave
        print(json.dumps(report, indent=2))
        if status == "fail":
            return 1
        if status == "deferred":
            return 3
        return 0

    # Human-readable output
    failed = False

    if all_hard:
        print("FAIL check_no_research_vocab (hard-ban):")
        for e in all_hard:
            print(e)
        failed = True

    if migration_violations:
        print("FAIL check_no_research_vocab (migration-guide import):")
        for v in migration_violations:
            print(f"  {v['file']}:{v['line']}: {v['text']}")
        failed = True

    if all_soft:
        if args.expiry_wave:
            print(f"DEFERRED check_no_research_vocab (soft-ban, expiry {args.expiry_wave}):")
        else:
            print("WARN check_no_research_vocab (soft-ban, expiry Wave 12):")
        for e in all_soft:
            print(e)

    if not failed:
        if all_soft:
            if args.expiry_wave:
                print(f"DEFERRED check_no_research_vocab (soft-ban deferred to {args.expiry_wave})")
                return 3
            print("OK check_no_research_vocab (soft-ban warnings above)")
        else:
            print("OK check_no_research_vocab")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())

