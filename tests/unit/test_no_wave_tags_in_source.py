"""Gate: hi_agent/**/*.py must not contain sprint wave labels as identifiers.

Wave-tagged identifiers (Wave 10.x, W5-F, W4-E, etc.) used as runtime
identifiers (variable names, string literals, enforcement strings) belong
in git commit messages and docs, not in production source code.

W31-D D-2': narrative comments that *describe* a wave-N fix (e.g.
``# W31-N (N.5): when allowlist_enabled is False ...``) are archaeological
documentation, not identifiers, and are exempted via the
``wave-literal-ok`` and ``expiry_wave:`` markers, plus a heuristic that
treats lines beginning with ``#`` as pure-narrative comments.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # repo root
HI_AGENT_SRC = ROOT / "hi_agent"
SCRIPTS_SRC = ROOT / "scripts"

_WAVE_PATTERN = re.compile(r"Wave\s+\d+\.\d+|W\d+-[A-Z]\b")
_LEGACY_ANNOTATION = "# legacy:"
_WAVE_LITERAL_OK = "wave-literal-ok"
_EXPIRY_WAVE = "expiry_wave"


def _scan_file(path: Path) -> list[str]:
    violations = []
    in_docstring = False
    docstring_quote: str | None = None
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        # Track docstring state. A line that opens AND closes the docstring
        # on itself does not toggle state.
        for quote in ('"""', "'''"):
            count = line.count(quote)
            if count == 0:
                continue
            if not in_docstring and count >= 2:
                # opens and closes on the same line — neutral
                continue
            if in_docstring and docstring_quote == quote:
                in_docstring = False
                docstring_quote = None
            elif not in_docstring:
                in_docstring = True
                docstring_quote = quote

        if not _WAVE_PATTERN.search(line):
            continue
        if _LEGACY_ANNOTATION in line:
            continue
        if _WAVE_LITERAL_OK in line:
            continue
        if _EXPIRY_WAVE in line:
            continue
        # Narrative-comment exemption: lines that are pure comments are
        # documentation, not identifiers (W31-D D-2').
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # In-docstring lines are narrative documentation.
        if in_docstring:
            continue
        # Lines that open a docstring count as narrative.
        if stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        violations.append(f"{path.relative_to(ROOT)}:{i}: {line.strip()}")
    return violations


def test_no_wave_tags_in_hi_agent_source():
    violations = []
    for py_file in HI_AGENT_SRC.rglob("*.py"):
        violations.extend(_scan_file(py_file))
    assert not violations, "Wave-tag identifiers found in source:\n" + "\n".join(violations)


def test_no_wave_tags_in_scripts():
    violations = []
    for py_file in SCRIPTS_SRC.rglob("*.py"):
        violations.extend(_scan_file(py_file))
    assert not violations, "Wave-tag identifiers found in scripts:\n" + "\n".join(violations)
