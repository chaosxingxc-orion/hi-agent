"""CLAUDE.md Rule Enforcement (DF-42).

Mechanically enforces the grep-based rules from CLAUDE.md that previously
relied on author discipline. Exits non-zero if any hard rule is violated.

Hard rules (exit non-zero on violation):
  * Rule 12    — no ``asyncio.run(...)`` outside entry points
  * Rule 13    — no inline ``or X(...)`` fallback for shared-state resources
  * Rule 13    — (scope) builders must not default ``profile_id=""``
  * Language   — no CJK in LLM-prompt-facing string literals

Soft rules (WARN only, exit stays 0):
  * Rule 7     — suspicious ``assert status in (..., "failed", ...)`` in tests

Runs with no external dependencies (pure stdlib ``re``/``ast``/``pathlib``),
so CI can invoke it on a fresh Python 3.12 without apt or pip installs.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parent.parent

SOURCE_ROOTS = ("hi_agent", "agent_kernel")

# Directories to skip wholesale.
SKIP_DIRS = frozenset({"venv", ".venv", "node_modules", ".git", "dist", "build", "__pycache__"})

# Entry-point file/path markers that may legally call asyncio.run.
ENTRYPOINT_FILENAMES = frozenset({"__main__.py"})
ENTRYPOINT_PATH_TOKENS = ("scripts/", "scripts\\", "/cli/", "\\cli\\")
ENTRYPOINT_FUNC_NAMES = frozenset(
    {"main", "_main", "cli", "_cli", "main_sync", "_main_sync", "run_sync"}
)

# Language Rule — replicated from tests/test_language_rule_enforcement.py.
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7a3]")
_LLM_CALL_NAMES = frozenset(
    {"complete", "acompletion", "generate", "agenerate", "invoke", "ainvoke", "query", "chat"}
)
_PROMPT_IDENTIFIERS = frozenset(
    {
        "prompt",
        "system_prompt",
        "user_prompt",
        "messages",
        "system_message",
        "DEFAULT_MEMORY_MESSAGE",
        "DEFAULT_SKILL_MESSAGE",
        "memory_nudge_message",
        "skill_nudge_message",
    }
)
_PROMPT_RETURNING_FUNCS = frozenset(
    {"format_results_for_context", "to_context_block", "_build_compression_prompt", "build_prompt"}
)

# Rule 13 — inline fallback to a shared-state resource constructor.
_RULE13_RE = re.compile(r" or [A-Z][A-Za-z]+(Store|Graph|Gateway|Manager|Engine|Registry)\(")

# Rule 13 scope — builder defaulting profile_id="".
_RULE13_SCOPE_RE = re.compile(r'def build_[a-z_]+\([^)]*profile_id[^)]*=\s*[\'\"][\'\"]')

# Rule 7 — test honesty heuristic (WARN).
_RULE7_RE = re.compile(
    r'''assert [^\n]+\.(status|state|result)\s+in\s+\([^)]*["']failed["'][^)]*\)'''
)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class RuleResult:
    rule_id: str
    description: str
    violations: list[str] = field(default_factory=list)
    is_warning: bool = False

    @property
    def passed(self) -> bool:
        return not self.violations

    def render(self, verbose: bool) -> str:
        if self.passed:
            return f"[PASS] {self.rule_id} ({self.description}): 0 violations"
        tag = "WARN" if self.is_warning else "FAIL"
        count_word = "potential violations (human review)" if self.is_warning else "violations"
        header = (
            f"[{tag}] {self.rule_id} ({self.description}): "
            f"{len(self.violations)} {count_word}"
        )
        body_lines = self.violations if verbose else self.violations[:10]
        body = "\n".join(f"  {v}" for v in body_lines)
        if not verbose and len(self.violations) > 10:
            body += f"\n  ... ({len(self.violations) - 10} more; use --verbose)"
        return header + "\n" + body


# --------------------------------------------------------------------------- #
# File enumeration
# --------------------------------------------------------------------------- #


def _iter_py_files(base: Path) -> list[Path]:
    out: list[Path] = []
    if not base.exists():
        return out
    for p in base.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return out


def _source_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        files.extend(_iter_py_files(repo / root))
    return files


def _test_files(repo: Path) -> list[Path]:
    return _iter_py_files(repo / "tests")


def _rel(path: Path, repo: Path) -> str:
    try:
        return str(path.relative_to(repo)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


# --------------------------------------------------------------------------- #
# Rule 12 — asyncio.run outside entry points
# --------------------------------------------------------------------------- #


def _is_entrypoint_file(path: Path) -> bool:
    if path.name in ENTRYPOINT_FILENAMES:
        return True
    sp = str(path).replace("\\", "/")
    return any(tok in sp for tok in ENTRYPOINT_PATH_TOKENS)


def _enclosing_function(tree: ast.AST, lineno: int) -> str | None:
    """Return name of the innermost function enclosing ``lineno`` (or None)."""
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= lineno <= end and (best is None or node.lineno > best[0]):
                best = (node.lineno, node.name)
    return best[1] if best else None


def check_rule_12(files: list[Path], repo: Path) -> RuleResult:
    result = RuleResult("Rule 12", "asyncio.run outside entry points")
    for path in files:
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_asyncio_run = (
                isinstance(func, ast.Attribute)
                and func.attr == "run"
                and isinstance(func.value, ast.Name)
                and func.value.id == "asyncio"
            )
            if not is_asyncio_run:
                continue
            if _is_entrypoint_file(path):
                continue
            enclosing = _enclosing_function(tree, node.lineno)
            if enclosing in ENTRYPOINT_FUNC_NAMES:
                continue
            result.violations.append(
                f"{_rel(path, repo)}:{node.lineno}: asyncio.run(...) outside "
                f"entry point (enclosing function: {enclosing or '<module>'})"
            )
    return result


# --------------------------------------------------------------------------- #
# Rule 13 — inline fallback construction
# --------------------------------------------------------------------------- #


def check_rule_13(files: list[Path], repo: Path) -> RuleResult:
    result = RuleResult("Rule 13", "inline fallback")
    for path in files:
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(src.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if _RULE13_RE.search(line):
                result.violations.append(
                    f"{_rel(path, repo)}:{lineno}: {line.strip()}"
                )
    return result


# --------------------------------------------------------------------------- #
# Rule 13 scope — builders must not default profile_id=""
# --------------------------------------------------------------------------- #


def check_rule_13_scope(repo: Path) -> RuleResult:
    result = RuleResult("Rule 13 scope", "required profile_id")
    base = repo / "hi_agent" / "config"
    for path in _iter_py_files(base):
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(src.splitlines(), start=1):
            if _RULE13_SCOPE_RE.search(line):
                result.violations.append(
                    f"{_rel(path, repo)}:{lineno}: {line.strip()}"
                )
    return result


# --------------------------------------------------------------------------- #
# Language Rule — CJK in LLM-prompt paths
# --------------------------------------------------------------------------- #


def _lang_collect(tree: ast.AST, path: Path, repo: Path) -> list[str]:
    violations: list[str] = []

    # 1. LLM-call arguments
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee: str | None = None
        if isinstance(node.func, ast.Attribute):
            callee = node.func.attr
        elif isinstance(node.func, ast.Name):
            callee = node.func.id
        if callee not in _LLM_CALL_NAMES:
            continue
        for arg in node.args:
            if (
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and _CJK_RE.search(arg.value)
            ):
                violations.append(
                    f"{_rel(path, repo)}:{arg.lineno}: CJK in LLM call "
                    f"'{callee}' argument: {arg.value[:60]!r}"
                )

    # 2. Prompt-identifier assignments
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        names: list[str] = []
        for t in targets:
            if isinstance(t, ast.Name):
                names.append(t.id)
            elif isinstance(t, ast.Attribute):
                names.append(t.attr)
        if not any(n in _PROMPT_IDENTIFIERS for n in names):
            continue
        for sub in ast.walk(value):
            if (
                isinstance(sub, ast.Constant)
                and isinstance(sub.value, str)
                and _CJK_RE.search(sub.value)
            ):
                violations.append(
                    f"{_rel(path, repo)}:{sub.lineno}: CJK in prompt assignment "
                    f"{names!r}: {sub.value[:60]!r}"
                )

    # 3. Returns from prompt-returning functions
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if func.name not in _PROMPT_RETURNING_FUNCS:
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Return) and node.value is not None:
                for sub in ast.walk(node.value):
                    if (
                        isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str)
                        and _CJK_RE.search(sub.value)
                    ):
                        violations.append(
                            f"{_rel(path, repo)}:{sub.lineno}: CJK in return "
                            f"from {func.name!r}: {sub.value[:60]!r}"
                        )

    return violations


def check_language_rule(files: list[Path], repo: Path) -> RuleResult:
    result = RuleResult("Language Rule", "no CJK in LLM prompts")
    for path in files:
        if "test_" in path.name:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            continue
        result.violations.extend(_lang_collect(tree, path, repo))
    return result


# --------------------------------------------------------------------------- #
# Rule 7 — test honesty heuristic (WARN only)
# --------------------------------------------------------------------------- #


def check_rule_7(repo: Path) -> RuleResult:
    result = RuleResult(
        "Rule 7 test honesty",
        "assert status in [...'failed'...]",
        is_warning=True,
    )
    for path in _test_files(repo):
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lines = src.splitlines()
        for lineno, line in enumerate(lines, start=1):
            if not _RULE7_RE.search(line):
                continue
            # Skip if the containing block (look upward 5 lines) is a
            # while/if guard loop — those legitimately poll for terminal state.
            lookback = "\n".join(lines[max(0, lineno - 6):lineno - 1])
            if re.search(r"\b(while|if)\b", lookback):
                continue
            result.violations.append(f"{_rel(path, repo)}:{lineno}: {line.strip()}")
    return result


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def run_checks(repo: Path) -> list[RuleResult]:
    src_files = _source_files(repo)
    return [
        check_rule_12(src_files, repo),
        check_rule_13(src_files, repo),
        check_rule_13_scope(repo),
        check_language_rule(src_files, repo),
        check_rule_7(repo),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CLAUDE.md rule enforcement (DF-42)")
    parser.add_argument("--verbose", action="store_true", help="show every violation line")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="repository root (default: this script's parent.parent)",
    )
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    results = run_checks(repo)

    for r in results:
        print(r.render(args.verbose))

    hard_fails = [r for r in results if not r.passed and not r.is_warning]
    total_hard = sum(1 for r in results if not r.is_warning)
    print()
    if hard_fails:
        print(f"OVERALL: FAIL ({len(hard_fails)} of {total_hard} hard rules failed)")
        return 1
    print(f"OVERALL: PASS ({total_hard} of {total_hard} hard rules passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
