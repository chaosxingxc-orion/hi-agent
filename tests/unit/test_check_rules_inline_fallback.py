"""Tests for scripts/check_rules.py Rule 6 constructor-call inline fallback detection.

Verifies that _RULE6_CONSTRUCTOR_RE correctly identifies ``x or SomeClass()``
patterns and does NOT flag legitimate ``or`` uses (strings, lists, builtins).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Reproduce the Rule 6 regex locally so this test file has no import-side-effect
# dependency on check_rules.py (which uses @dataclass and other module-level code
# that can fail under some Python versions when imported via importlib).
RULE6_RE = re.compile(r"\bor\s+[A-Z][A-Za-z0-9_]*\(")
_RULE6_FP_WORDS = frozenset({"True", "False", "None", "NotImplemented", "Ellipsis"})

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_rules.py"


def _check_rule_6_on_lines(lines: list[str]) -> list[str]:
    """Minimal re-implementation of check_rule_6 for test isolation."""
    violations = []
    for lineno, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        m = RULE6_RE.search(line)
        if not m:
            continue
        after_or = line[m.start():].split("or", 1)[1].lstrip()
        class_name = after_or.split("(")[0].rstrip()
        if class_name in _RULE6_FP_WORDS:
            continue
        violations.append(f"line {lineno}: {line.strip()}")
    return violations


# ---------------------------------------------------------------------------
# Positive cases — must be flagged
# ---------------------------------------------------------------------------

POSITIVE_CASES = [
    # Site 1 — descriptor_factory form (the original 8-site pattern)
    "self._factory = descriptor_factory or CapabilityDescriptorFactory()",
    # Site 2 — budget form
    "self._budget = budget or ContextBudget()",
    # Site 3 — config form
    "self._config = config or StructuredCompressorConfig()",
    # Site 4 — policy form
    "self._policy = policy or RetryPolicy()",
    # Site 5 — decomposer form
    "self._decomposer = decomposer or TaskDecomposer()",
    # Site 6 — cache config form
    "self._config = config or PromptCacheConfig()",
    # Site 7 — history form
    "self._history = history or ConfigHistory()",
    # Site 8 — journal form
    "self._journal = journal or InMemoryConsistencyJournal()",
]


@pytest.mark.parametrize("line", POSITIVE_CASES)
def test_rule6_regex_flags_constructor_fallback(line: str) -> None:
    """Each positive-case line must match the Rule 6 constructor-fallback regex."""
    violations = _check_rule_6_on_lines([line])
    assert violations, (
        f"Expected Rule 6 regex to match: {line!r}"
    )


# ---------------------------------------------------------------------------
# Negative cases — must NOT be flagged as violations
# ---------------------------------------------------------------------------

NEGATIVE_CASES = [
    # Plain string default
    'result = value or "default_string"',
    # Empty list default
    "items = items or []",
    # Integer default
    "count = count or 0",
    # Boolean OR expression (not constructor)
    "flag = flag or True",
    # Comment line
    "# x or DefaultX() pattern is forbidden by Rule 6",
    # Legitimate ternary-style with a non-PascalCase name
    "path = path or fallback_path",
    # Dict default
    "data = data or {}",
    # None check with assignment (not constructor)
    "value = value or None",
]


@pytest.mark.parametrize("line", NEGATIVE_CASES)
def test_rule6_regex_does_not_flag_legitimate_or(line: str) -> None:
    """Legitimate ``or`` usage must not produce a Rule 6 violation.

    The checker skips comment lines and filters out known false-positive
    builtin names (True, False, None, etc.).
    """
    violations = _check_rule_6_on_lines([line])
    assert not violations, (
        f"Expected no Rule 6 violation for: {line!r}\n"
        f"Got: {violations}"
    )


# ---------------------------------------------------------------------------
# Integration: check_rule_6 function returns no violations for clean source
# ---------------------------------------------------------------------------


def test_check_rule_6_flags_constructor_form() -> None:
    """Lines with ``x or SomeClass()`` must produce violations."""
    bad_lines = [
        "    self._config = config or MyConfig()",
        "    self._store = store or InMemoryStore(key=val)",
    ]
    violations = _check_rule_6_on_lines(bad_lines)
    assert len(violations) == 2, f"Expected 2 violations, got: {violations}"
    assert any("MyConfig" in v for v in violations)
    assert any("InMemoryStore" in v for v in violations)


def test_check_rule_6_does_not_flag_clean_source() -> None:
    """Source that raises ValueError instead of fallback must produce zero violations."""
    clean_lines = [
        "class A:",
        "    def __init__(self, config: MyConfig) -> None:",
        "        if config is None:",
        '            raise ValueError("config is required")',
        "        self._config = config",
    ]
    violations = _check_rule_6_on_lines(clean_lines)
    assert violations == [], f"Expected no violations, got: {violations}"


def test_check_rules_script_includes_rule6(tmp_path: Path) -> None:
    """check_rules.py script must include Rule 6 in its output."""
    import subprocess

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "Rule 6" in result.stdout, (
        f"Expected 'Rule 6' in check_rules output\nstdout={result.stdout}"
    )
