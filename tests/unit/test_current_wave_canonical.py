"""Wave-canonical alignment guard (W32 Track F #4a).

Audit finding (W32, Track F #4a): two wave files diverged.
    docs/current-wave.txt          → 32 (canonical, used by scripts/_governance/wave.py)
    docs/governance/current-wave.txt → 31 (stale, read by 4 gate scripts)

Reading the stale governance copy in `check_gate_strictness.py`,
`check_manifest_budget.py`, `check_pytest_skip_discipline.py`, and
`check_rule7_observability.py` produced inconsistent expiry-wave evaluations
(W31 expiries treated as future when current was actually W32).

Fix: all gate scripts now read `docs/current-wave.txt` directly, and the
governance copy is bumped in lockstep so any remaining external reader
sees the same value.

This test is the regression guard:
    1. The two files MUST contain the same parseable wave number.
    2. Both MUST equal `current_wave_number()` from the canonical helper.
    3. No script under `scripts/` may read `docs/governance/current-wave.txt`
       any more — the canonical path is `docs/current-wave.txt`.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CANONICAL_FILE = REPO_ROOT / "docs" / "current-wave.txt"
GOVERNANCE_FILE = REPO_ROOT / "docs" / "governance" / "current-wave.txt"
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _read_int(path: pathlib.Path) -> int:
    text = path.read_text(encoding="utf-8").strip()
    m = re.match(r"^(\d+)$", text)
    if not m:
        pytest.fail(f"{path} does not contain a single integer wave number: {text!r}")
    return int(m.group(1))


def test_current_wave_files_agree() -> None:
    """docs/current-wave.txt and docs/governance/current-wave.txt must agree."""
    canonical = _read_int(CANONICAL_FILE)
    governance = _read_int(GOVERNANCE_FILE)
    assert canonical == governance, (
        f"Wave drift: docs/current-wave.txt={canonical} but "
        f"docs/governance/current-wave.txt={governance}. "
        "Both must equal the current wave; bump in lockstep."
    )


def test_current_wave_matches_canonical_helper() -> None:
    """The canonical loader and the file must agree."""
    from scripts._governance.wave import current_wave_number  # type: ignore[import-not-found]

    helper_value = current_wave_number()
    canonical = _read_int(CANONICAL_FILE)
    assert helper_value == canonical, (
        f"Canonical helper returned {helper_value} but docs/current-wave.txt={canonical}. "
        "scripts/_governance/wave.py is the only authoritative loader."
    )


_GOVERNANCE_PATH_RE = re.compile(
    r'docs[\\/]+governance[\\/]+current-wave\.txt',
    re.IGNORECASE,
)


def test_no_script_reads_stale_governance_path() -> None:
    """No file under scripts/ may reference docs/governance/current-wave.txt.

    The 4 BLOCKER scripts that previously read it (check_gate_strictness.py,
    check_manifest_budget.py, check_pytest_skip_discipline.py,
    check_rule7_observability.py) were migrated to docs/current-wave.txt in
    Wave 32. This guard prevents regression.
    """
    offenders: list[str] = []
    for py_file in sorted(SCRIPTS_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            # Skip comments — comments may legitimately mention the legacy path
            # in incident-history annotations without re-introducing the bug.
            if stripped.startswith("#"):
                continue
            if _GOVERNANCE_PATH_RE.search(line):
                rel = py_file.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, (
        "Found scripts/ files reading docs/governance/current-wave.txt. "
        "Use docs/current-wave.txt (canonical) instead.\n"
        + "\n".join(offenders)
    )
