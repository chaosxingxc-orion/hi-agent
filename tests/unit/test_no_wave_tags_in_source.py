"""Gate: hi_agent/**/*.py must not contain sprint wave labels.

Wave-tagged identifiers (Wave 10.x, W5-F, W4-E, etc.) belong in git commit
messages and docs, not in production source code.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # repo root
HI_AGENT_SRC = ROOT / "hi_agent"
SCRIPTS_SRC = ROOT / "scripts"

_WAVE_PATTERN = re.compile(r"Wave\s+\d+\.\d+|W\d+-[A-Z]\b")
_LEGACY_ANNOTATION = "# legacy:"


def _scan_file(path: Path) -> list[str]:
    violations = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if _WAVE_PATTERN.search(line) and _LEGACY_ANNOTATION not in line:
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
