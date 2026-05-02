#!/usr/bin/env python
"""W31-N4: facade-seam annotation gate.

Walks every ``.py`` file under ``agent_server/facade/**`` and asserts
that any ``from hi_agent.`` import is annotated with the comment
``# r-as-1-seam: <reason>`` either on the same line or on the
immediately preceding line. The bootstrap module
(``agent_server/bootstrap.py``) is exempt — it is the canonical seam by
design (W31-N1).

Why a separate gate from check_layering.py: the facade modules MUST
reach into hi_agent (that's their entire purpose — to wrap a hi_agent
class behind an agent_server contract). What we want to enforce is that
each such reach is *intentional and documented*. The annotation comment
forces the author to name the boundary they're crossing and gives
reviewers a single string to grep when they audit R-AS-1.

Usage::

    python scripts/check_facade_seams.py            # human-readable
    python scripts/check_facade_seams.py --json     # multistatus JSON

Exit 0 = PASS; 1 = FAIL.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACADE_DIR = ROOT / "agent_server" / "facade"
EXEMPT_FILES = frozenset({"agent_server/bootstrap.py"})

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit  # noqa: E402  # expiry_wave: permanent  # added: W31 (governance utility/test helper)

_FROM_HI_AGENT_PATTERN = re.compile(r"^\s*from\s+hi_agent\.")
_SEAM_ANNOTATION = re.compile(r"#\s*r-as-1-seam\s*:\s*(.+)$")


def _is_exempt(rel_path: str) -> bool:
    return rel_path in EXEMPT_FILES


def _scan_file(path: Path) -> list[dict[str, object]]:
    """Return the list of unannotated ``from hi_agent.`` imports in ``path``.

    Each entry: ``{file, line, source}``. Empty list = file is clean.
    """
    rel_path = path.relative_to(ROOT).as_posix()
    if _is_exempt(rel_path):
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:  # pragma: no cover - defensive
        return []

    violations: list[dict[str, object]] = []
    for idx, raw in enumerate(lines):
        if not _FROM_HI_AGENT_PATTERN.match(raw):
            continue
        # Same-line annotation? Look for the seam marker anywhere on the line
        # (including in a trailing comment after the import statement).
        if _SEAM_ANNOTATION.search(raw):
            continue
        # Otherwise the previous non-blank line must carry the annotation.
        prev_idx = idx - 1
        while prev_idx >= 0 and not lines[prev_idx].strip():
            prev_idx -= 1
        if prev_idx >= 0 and _SEAM_ANNOTATION.search(lines[prev_idx]):
            continue
        violations.append(
            {
                "file": rel_path,
                "line": idx + 1,
                "source": raw.rstrip(),
            }
        )
    return violations


def evaluate() -> GateResult:
    """Scan agent_server/facade/** for unannotated hi_agent imports."""
    if not FACADE_DIR.exists():
        return GateResult(
            status=GateStatus.PASS,
            gate_name="facade_seams",
            reason="agent_server/facade not yet created (vacuous PASS)",
            evidence={"facade_dir_exists": False},
        )

    all_violations: list[dict[str, object]] = []
    files_scanned = 0
    for dirpath, dirnames, filenames in os.walk(FACADE_DIR):
        dirnames[:] = [d for d in dirnames if d not in {"__pycache__"}]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            files_scanned += 1
            all_violations.extend(_scan_file(Path(dirpath) / filename))

    if all_violations:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="facade_seams",
            reason=(
                f"{len(all_violations)} unannotated hi_agent import(s) under "
                "agent_server/facade/ — every cross-boundary import must carry "
                "'# r-as-1-seam: <reason>' on the same or immediately preceding line"
            ),
            evidence={
                "violations": all_violations,
                "files_scanned": files_scanned,
            },
        )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="facade_seams",
        reason=(
            f"all hi_agent imports under agent_server/facade ({files_scanned} files) "
            "carry r-as-1-seam annotations"
        ),
        evidence={"violations": [], "files_scanned": files_scanned},
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="W31-N4: facade-seam annotation gate."
    )
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    result = evaluate()
    if args.json:
        emit(result)  # exits

    if result.status is GateStatus.PASS:
        print(f"PASS (W31-N4): {result.reason}")
        return 0
    print(f"FAIL (W31-N4): {result.reason}")
    for v in result.evidence.get("violations", []):
        print(f"  {v['file']}:{v['line']}  {v['source']}")
    print(
        "\nFix: add '# r-as-1-seam: <reason>' on the same line as the import\n"
        "or on the line immediately above it."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
