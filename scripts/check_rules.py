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
  * Rule 6     — constructor-call inline fallback (x or ClassName())

Runs with no external dependencies (pure stdlib ``re``/``ast``/``pathlib``),
so CI can invoke it on a fresh Python 3.12 without apt or pip installs.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
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

# Rule 13 — inline fallback suffixes for shared-state resources (used by AST check).
_RULE13_SHARED_SUFFIXES = frozenset({
    "Store", "Graph", "Gateway", "Manager", "Engine", "Registry",
    "Pool", "Bridge", "Adapter", "Client", "Session",
})

# Rule 6 — stdlib/primitive type names that are NOT shared-state resources.
_RULE6_STDLIB_SAFE = frozenset({
    "Path", "RuntimeError", "ValueError", "TypeError", "KeyError",
    "AttributeError", "IndexError", "OSError", "IOError", "Exception",
    "BaseException", "NotImplementedError", "StopIteration",
    "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "True", "False", "None",
})

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
# AST helpers — docstring line-set and shared BoolOp/Or visitor
# --------------------------------------------------------------------------- #


def _docstring_linenos(tree: ast.AST) -> frozenset[int]:
    """Return the set of line numbers that belong to a docstring constant."""
    linenos: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            end = getattr(first, "end_lineno", first.lineno)
            for ln in range(first.lineno, end + 1):
                linenos.add(ln)
    return frozenset(linenos)


def _find_rule6_violations_ast(source: str, path: str) -> list[tuple[int, str]]:
    """Find ``x or SomeClass(...)`` patterns that may be Rule 6 inline fallbacks.

    Skips:
    - docstrings (Expr(Constant(str)) at body position 0)
    - ExceptHandler bodies (exception construction is not a shared-state fallback)
    - stdlib / primitive type names listed in _RULE6_STDLIB_SAFE
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    docstring_lines = _docstring_linenos(tree)
    violations: list[tuple[int, str]] = []
    src_lines = source.splitlines()

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._in_except = False

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            old = self._in_except
            self._in_except = True
            self.generic_visit(node)
            self._in_except = old

        def visit_BoolOp(self, node: ast.BoolOp) -> None:
            if isinstance(node.op, ast.Or) and not self._in_except:
                for value in node.values:
                    if isinstance(value, ast.Call):
                        func = value.func
                        name: str | None = None
                        if isinstance(func, ast.Name):
                            name = func.id
                        elif isinstance(func, ast.Attribute):
                            name = func.attr
                        if name and name[0].isupper() and name not in _RULE6_STDLIB_SAFE:
                            ln = getattr(node, "lineno", 0)
                            if ln not in docstring_lines:
                                src_line = src_lines[ln - 1] if ln else ""
                                violations.append((ln, src_line.strip()))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return violations


def _find_rule13_violations_ast(source: str, path: str) -> list[tuple[int, str]]:
    """Find ``x or SomeClass(...)`` where SomeClass ends with a shared-state suffix.

    Same suppression rules as Rule 6: skips docstrings and ExceptHandler bodies.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    docstring_lines = _docstring_linenos(tree)
    violations: list[tuple[int, str]] = []
    src_lines = source.splitlines()

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._in_except = False

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            old = self._in_except
            self._in_except = True
            self.generic_visit(node)
            self._in_except = old

        def visit_BoolOp(self, node: ast.BoolOp) -> None:
            if isinstance(node.op, ast.Or) and not self._in_except:
                for value in node.values:
                    if isinstance(value, ast.Call):
                        func = value.func
                        name: str | None = None
                        if isinstance(func, ast.Name):
                            name = func.id
                        elif isinstance(func, ast.Attribute):
                            name = func.attr
                        if name and any(name.endswith(s) for s in _RULE13_SHARED_SUFFIXES):
                            ln = getattr(node, "lineno", 0)
                            if ln not in docstring_lines:
                                src_line = src_lines[ln - 1] if ln else ""
                                violations.append((ln, src_line.strip()))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return violations


# --------------------------------------------------------------------------- #
# Rule 6 — constructor-call inline fallback: ``x or SomeClass()``
# --------------------------------------------------------------------------- #


def check_rule_6(files: list[Path], repo: Path) -> RuleResult:
    """Check for constructor-call inline fallbacks: ``x or SomeClass(...)``.

    Uses AST-based detection to skip docstrings, ExceptHandler bodies, and
    stdlib/primitive type names.  Warning-mode: flags sites for manual review.
    Fixed sites in hi_agent/ should not appear here; remaining agent_kernel/
    sites are tracked as pre-existing debt.
    """
    result = RuleResult(
        "Rule 6",
        "constructor-call inline fallback (x or ClassName())",
        is_warning=True,
    )
    for path in files:
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, text in _find_rule6_violations_ast(src, str(path)):
            result.violations.append(f"{_rel(path, repo)}:{lineno}: {text}")
    return result


# --------------------------------------------------------------------------- #
# Rule 13 — inline fallback construction
# --------------------------------------------------------------------------- #


def check_rule_13(files: list[Path], repo: Path) -> RuleResult:
    """Check for inline fallbacks to shared-state resource constructors.

    Uses AST-based detection to skip docstrings and ExceptHandler bodies.
    Flags class names whose suffix matches _RULE13_SHARED_SUFFIXES.
    """
    result = RuleResult("Rule 13", "inline fallback")
    for path in files:
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, text in _find_rule13_violations_ast(src, str(path)):
            result.violations.append(f"{_rel(path, repo)}:{lineno}: {text}")
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
        check_rule_6(src_files, repo),
        check_rule_12(src_files, repo),
        check_rule_13(src_files, repo),
        check_rule_13_scope(repo),
        check_language_rule(src_files, repo),
        check_rule_7(repo),
    ]


def _git_head_sha(repo: Path) -> str:
    """Return the current HEAD SHA (short), or 'unknown' if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CLAUDE.md rule enforcement (DF-42)")
    parser.add_argument("--verbose", action="store_true", help="show every violation line")
    parser.add_argument(
        "--json", action="store_true", help="emit JSON output to stdout after checks"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="repository root (default: this script's parent.parent)",
    )
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    results = run_checks(repo)

    hard_fails = [r for r in results if not r.passed and not r.is_warning]
    total_hard = sum(1 for r in results if not r.is_warning)

    if not args.json:
        for r in results:
            print(r.render(args.verbose))
        print()
        if hard_fails:
            print(f"OVERALL: FAIL ({len(hard_fails)} of {total_hard} hard rules failed)")
        else:
            print(f"OVERALL: PASS ({total_hard} of {total_hard} hard rules passed)")
    else:
        # Collect Rule 6 and Rule 13 warning sites for JSON output.
        rule6_result = next((r for r in results if r.rule_id == "Rule 6"), None)
        rule13_result = next((r for r in results if r.rule_id == "Rule 13"), None)

        def _parse_sites(violations: list[str]) -> list[dict]:
            sites = []
            for v in violations:
                # Format: "path/to/file.py:42: source text"
                parts = v.split(":", 2)
                if len(parts) >= 2:
                    file_part = parts[0]
                    try:
                        line_num = int(parts[1])
                    except ValueError:
                        line_num = 0
                    text_part = parts[2].strip() if len(parts) > 2 else ""
                    sites.append({"file": file_part, "line": line_num, "text": text_part})
            return sites

        r6_violations = rule6_result.violations if rule6_result else []
        r13_violations = rule13_result.violations if rule13_result else []

        payload = {
            "check": "rules",
            "status": "fail" if hard_fails else "pass",
            "violations": [
                {"rule": r.rule_id, "description": r.description, "sites": r.violations}
                for r in hard_fails
            ],
            "hard_pass": not bool(hard_fails),
            "rule6_warnings": {
                "count": len(r6_violations),
                "sites": _parse_sites(r6_violations),
            },
            "rule13_warnings": {
                "count": len(r13_violations),
                "sites": _parse_sites(r13_violations),
            },
            "head": _git_head_sha(repo),
        }
        print(json.dumps(payload, indent=2))

    return 1 if hard_fails else 0


if __name__ == "__main__":
    sys.exit(main())
