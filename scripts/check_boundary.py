#!/usr/bin/env python
"""Boundary checker for hi_agent <-> agent_kernel separation.

Three rules are enforced:

B-1 (reverse import): No agent_kernel/**/*.py may import from hi_agent.
B-2 (adapter bypass): No hi_agent/**/*.py outside hi_agent/runtime_adapter/**
    may import from agent_kernel, except hi_agent/testing/** may import from
    agent_kernel.testing, and hi_agent/skills/** may import agent_kernel DTOs
    (kernel public surface).
B-3 (hardcoded model): No agent_kernel/**/*.py may contain model/provider
    strings (gpt-, claude-, volces, doubao) in non-comment, non-docstring code.

Usage:
    python scripts/check_boundary.py [--strict]

Exit code 0 if zero violations, exit code 1 if any violations found.
--strict is an alias for the default behavior (kept for future use).
"""

from __future__ import annotations

import argparse
import ast
import io
import sys
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

HARDCODED_MODEL_STRINGS = ("gpt-", "claude-", "volces", "doubao")


def _iter_python_files(directory: Path):
    yield from sorted(directory.rglob("*.py"))


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _read_source(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _get_import_lines(source: str, path: Path) -> list[tuple[int, str]]:
    """Return (lineno, line_text) for lines containing import statements."""
    results: list[tuple[int, str]] = []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # Fall back to line-by-line scan for broken files
        for lineno, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                results.append((lineno, stripped))
        return results

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            results.append((node.lineno, f"from {module} import ..."))
    return results


def _imports_hi_agent(source: str, path: Path) -> list[tuple[int, str]]:
    """Return import lines that reference hi_agent."""
    hits = []
    for lineno, text in _get_import_lines(source, path):
        if "hi_agent" in text:
            hits.append((lineno, text))
    return hits


def _imports_agent_kernel(source: str, path: Path) -> list[tuple[int, str]]:
    """Return import lines that reference agent_kernel."""
    hits = []
    for lineno, text in _get_import_lines(source, path):
        if "agent_kernel" in text:
            hits.append((lineno, text))
    return hits


def _is_in_docstring_or_comment_heuristic(source: str) -> set[int]:
    """Return set of line numbers that are inside triple-quoted strings or are comments.

    This is a heuristic using the tokenizer; false negatives are acceptable,
    false positives are not (per spec).
    """
    excluded_set: set[int] = set()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return excluded_set

    for tok_type, tok_string, tok_start, tok_end, _ in tokens:
        start_line = tok_start[0]
        end_line = tok_end[0]
        if tok_type == tokenize.COMMENT:
            excluded_set.add(start_line)
        elif tok_type == tokenize.STRING and tok_string.startswith(
            ('"""', "'''", 'r"""', "r'''")
        ):
            for lineno in range(start_line, end_line + 1):
                excluded_set.add(lineno)
    return excluded_set


def _find_hardcoded_model_strings(source: str, path: Path) -> list[tuple[int, str]]:
    """Return (lineno, description) for hardcoded model/provider strings in non-comment,
    non-docstring code."""
    excluded_lines = _is_in_docstring_or_comment_heuristic(source)
    hits = []
    for lineno, line in enumerate(source.splitlines(), 1):
        if lineno in excluded_lines:
            continue
        # Also skip pure comment lines (starts with # after optional whitespace)
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for needle in HARDCODED_MODEL_STRINGS:
            if needle in line:
                hits.append((lineno, f"contains {needle!r}: {stripped[:120]}"))
                break  # one violation per line is enough
    return hits


def check_b1(agent_kernel_dir: Path) -> list[str]:
    """B-1: No agent_kernel file may import from hi_agent."""
    violations: list[str] = []
    if not agent_kernel_dir.exists():
        return violations
    for path in _iter_python_files(agent_kernel_dir):
        source = _read_source(path)
        if source is None:
            continue
        for lineno, text in _imports_hi_agent(source, path):
            rel = _relative(path)
            violations.append(
                f"VIOLATION [B-1] {rel}:{lineno}: reverse import from hi_agent: {text}"
            )
    return violations


def check_b2(hi_agent_dir: Path) -> list[str]:
    """B-2: hi_agent files outside runtime_adapter may not import agent_kernel,
    except:
    - hi_agent/testing may import agent_kernel.testing
    - hi_agent/skills may import agent_kernel DTOs (public kernel surface)
    """
    violations: list[str] = []
    if not hi_agent_dir.exists():
        return violations

    runtime_adapter_dir = hi_agent_dir / "runtime_adapter"
    testing_dir = hi_agent_dir / "testing"
    skills_dir = hi_agent_dir / "skills"

    for path in _iter_python_files(hi_agent_dir):
        # Files inside runtime_adapter are allowed
        try:
            path.relative_to(runtime_adapter_dir)
            continue
        except ValueError:
            pass

        # Files inside hi_agent/skills are allowed (kernel DTOs are public surface)
        try:
            path.relative_to(skills_dir)
            continue
        except ValueError:
            pass

        source = _read_source(path)
        if source is None:
            continue

        in_testing = False
        try:
            path.relative_to(testing_dir)
            in_testing = True
        except ValueError:
            pass

        for lineno, text in _imports_agent_kernel(source, path):
            # Testing files may import agent_kernel.testing only
            if in_testing and "agent_kernel.testing" in text:
                continue
            rel = _relative(path)
            violations.append(
                f"VIOLATION [B-2] {rel}:{lineno}: adapter bypass — "
                f"hi_agent file outside runtime_adapter imports agent_kernel: {text}"
            )
    return violations


def check_b3(agent_kernel_dir: Path) -> list[str]:
    """B-3: No agent_kernel file may hardcode model/provider strings in non-comment,
    non-docstring code."""
    violations: list[str] = []
    if not agent_kernel_dir.exists():
        return violations
    for path in _iter_python_files(agent_kernel_dir):
        source = _read_source(path)
        if source is None:
            continue
        for lineno, description in _find_hardcoded_model_strings(source, path):
            rel = _relative(path)
            violations.append(
                f"VIOLATION [B-3] {rel}:{lineno}: "
                f"hardcoded model/provider string — {description}"
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check hi_agent <-> agent_kernel boundary")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Alias for default behavior (exit 1 on violations); kept for future use.",
    )
    parser.parse_args(argv)

    agent_kernel_dir = REPO_ROOT / "agent_kernel"
    hi_agent_dir = REPO_ROOT / "hi_agent"

    all_violations: list[str] = []
    all_violations.extend(check_b1(agent_kernel_dir))
    all_violations.extend(check_b2(hi_agent_dir))
    all_violations.extend(check_b3(agent_kernel_dir))

    for v in all_violations:
        print(v)

    count = len(all_violations)
    print(f"{count} violation(s) found.")

    return 0 if count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
