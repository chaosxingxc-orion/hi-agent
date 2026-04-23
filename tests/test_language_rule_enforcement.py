"""Language Rule static guard (DF-15 / K-14).

Enforces CLAUDE.md's Language Rule: no Chinese/Japanese/Korean characters in
string literals that reach an LLM prompt. This is a best-effort static check —
not a proof of correctness — but it catches the common patterns under which
the violation crept in (DF-15: ``delegation.py`` context-block builder;
``structured_compression.py`` compression prompt; ``nudge.py`` default nudge
messages).

Heuristics:

1. Scan every non-test ``.py`` file under ``hi_agent/``.
2. For each ``ast.Constant`` string literal, flag it when *either* of these
   hold:

   * The literal appears as an argument to a function call whose attribute
     or name matches a known LLM-facing surface
     (``complete``, ``generate``, ``invoke``, ``ainvoke``, ``query``,
     ``chat``, ``acompletion``).
   * The literal is assigned (directly or via an augmented/annotated
     assignment) to a target whose name matches a known prompt-carrying
     identifier (``prompt``, ``system_prompt``, ``user_prompt``,
     ``messages``, ``system_message``, ``default_memory_message``,
     ``default_skill_message``, ``memory_nudge_message``,
     ``skill_nudge_message``).
   * The literal is returned from a function whose name contains
     ``prompt`` or ``to_context_block`` or ``format_results_for_context``
     or ``_build_compression_prompt`` (covers the three known sinks).

3. Module- / class- / function-level docstrings are ignored (they do not
   reach the model).
4. Comments are ignored by ``ast`` automatically.

The CJK character range covered here is BMP CJK Unified Ideographs
(U+4E00 to U+9FFF), Hiragana (U+3040 to U+309F), Katakana
(U+30A0 to U+30FF), and Hangul Syllables (U+AC00 to U+D7A3).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7a3]")

# Names of callables whose string arguments are LLM prompts.
_LLM_CALL_NAMES: frozenset[str] = frozenset(
    {
        "complete",
        "acompletion",
        "generate",
        "agenerate",
        "invoke",
        "ainvoke",
        "query",
        "chat",
    }
)

# Assignment-target names that indicate an LLM-facing prompt string.
_PROMPT_IDENTIFIERS: frozenset[str] = frozenset(
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

# Function names whose return value is fed into a TaskView (and thus an LLM).
_PROMPT_RETURNING_FUNCS: frozenset[str] = frozenset(
    {
        "format_results_for_context",
        "to_context_block",
        "_build_compression_prompt",
        "build_prompt",
    }
)

_HI_AGENT_ROOT = Path(__file__).resolve().parent.parent / "hi_agent"


def _iter_py_files() -> list[Path]:
    return [p for p in _HI_AGENT_ROOT.rglob("*.py") if "test_" not in p.name]


def _is_docstring(node: ast.AST, parent: ast.AST | None) -> bool:
    """Return True if *node* is the docstring of *parent*.

    A docstring is the first statement of a module/class/function and
    consists solely of an ``Expr(Constant(str))``.
    """
    if not isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    body = getattr(parent, "body", [])
    if not body:
        return False
    first = body[0]
    if not isinstance(first, ast.Expr):
        return False
    return first.value is node


def _collect_violations(tree: ast.AST, source_path: Path) -> list[str]:
    violations: list[str] = []

    # --- 1. LLM-call arguments -----------------------------------------
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            callee: str | None = None
            if isinstance(func, ast.Attribute):
                callee = func.attr
            elif isinstance(func, ast.Name):
                callee = func.id
            if callee not in _LLM_CALL_NAMES:
                continue
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and _CJK_RE.search(arg.value)
                ):
                    violations.append(
                        f"{source_path}:{arg.lineno}: CJK in LLM call '{callee}' argument: "
                        f"{arg.value[:60]!r}"
                    )

    # --- 2. Assignments to prompt-named targets ------------------------
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

        target_names: list[str] = []
        for t in targets:
            if isinstance(t, ast.Name):
                target_names.append(t.id)
            elif isinstance(t, ast.Attribute):
                target_names.append(t.attr)

        if not any(name in _PROMPT_IDENTIFIERS for name in target_names):
            continue

        # Walk value for embedded string constants.
        for sub in ast.walk(value):
            if (
                isinstance(sub, ast.Constant)
                and isinstance(sub.value, str)
                and _CJK_RE.search(sub.value)
            ):
                violations.append(
                    f"{source_path}:{sub.lineno}: CJK in prompt-identifier assignment "
                    f"{target_names!r}: {sub.value[:60]!r}"
                )

    # --- 3. Returns from prompt-returning functions --------------------
    for func_node in ast.walk(tree):
        if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if func_node.name not in _PROMPT_RETURNING_FUNCS:
            continue
        for node in ast.walk(func_node):
            if isinstance(node, ast.Return) and node.value is not None:
                for sub in ast.walk(node.value):
                    if (
                        isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str)
                        and _CJK_RE.search(sub.value)
                    ):
                        violations.append(
                            f"{source_path}:{sub.lineno}: CJK in return from "
                            f"{func_node.name!r}: {sub.value[:60]!r}"
                        )

    return violations


def test_no_cjk_in_llm_prompt_paths() -> None:
    """No Chinese/Japanese/Korean characters in strings that reach an LLM.

    Fails with a comprehensive list if any site is detected. See the module
    docstring for the exact heuristics.
    """
    all_violations: list[str] = []
    for py_file in _iter_py_files():
        try:
            source = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - defensive
            all_violations.append(f"{py_file}: unreadable as UTF-8 ({exc})")
            continue
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError as exc:  # pragma: no cover - defensive
            all_violations.append(f"{py_file}: parse error ({exc})")
            continue
        all_violations.extend(_collect_violations(tree, py_file))

    assert not all_violations, (
        "Language Rule (CLAUDE.md) violations — LLM-facing strings must be "
        "English. Found:\n  " + "\n  ".join(all_violations)
    )
