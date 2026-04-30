#!/usr/bin/env python3
"""CI gate: state-machine transitions have test coverage (AX-B B4).

Checks that tests/integration/test_run_state_transition_matrix.py
exists and contains at least MIN_TRANSITIONS parametrized transition rows.

Exit 0: PASS
Exit 1: FAIL
Exit 2: not_applicable (test file absent, non-strict mode)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX_TEST = ROOT / "tests" / "integration" / "test_run_state_transition_matrix.py"

# Minimum number of transition rows required to consider coverage adequate.
MIN_TRANSITIONS = 10

# Pattern that matches a TRANSITIONS tuple entry:
#   ("FROM_STATE", "TO_STATE", "scenario_label")
_TRANSITION_ROW = re.compile(
    r'\(\s*"([A-Z_]+)"\s*,\s*"([A-Z_]+)"\s*,\s*"[^"]*"\s*\)',
)


def _count_transitions(src: str) -> list[tuple[str, str]]:
    """Return list of (from_state, to_state) pairs found in the source."""
    return [(m.group(1), m.group(2)) for m in _TRANSITION_ROW.finditer(src)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CI gate: state-transition matrix test has sufficient coverage."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON result instead of human text"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 (FAIL) instead of 2 (not_applicable) when test file is absent",
    )
    parser.add_argument(
        "--min-transitions",
        type=int,
        default=MIN_TRANSITIONS,
        help=f"Minimum number of transition rows required (default: {MIN_TRANSITIONS})",
    )
    args = parser.parse_args()
    min_required = args.min_transitions

    def _emit(result: dict, exit_code: int) -> int:
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            status = result["status"].upper()
            msg = result.get("reason") or f"{result.get('transitions_covered', '?')} transitions covered"  # noqa: E501  # expiry_wave: Wave 27  # added: W25 baseline sweep
            print(f"{status}: {msg}")
        return exit_code

    if not MATRIX_TEST.exists():
        status = "fail" if args.strict else "not_applicable"
        return _emit(
            {
                "status": status,
                "check": "state_transition_coverage",
                "reason": "test_run_state_transition_matrix.py not found",
            },
            1 if status == "fail" else 2,
        )

    src = MATRIX_TEST.read_text(encoding="utf-8", errors="replace")
    transitions = _count_transitions(src)

    if len(transitions) < min_required:
        return _emit(
            {
                "status": "fail",
                "check": "state_transition_coverage",
                "transitions_found": len(transitions),
                "min_required": min_required,
                "reason": (
                    f"only {len(transitions)} transition rows found "
                    f"(require >= {min_required})"
                ),
            },
            1,
        )

    # Bonus: verify RunState membership if importable.
    state_check: dict = {}
    try:
        from hi_agent.contracts.run import RunState

        valid_names = {s.name for s in RunState}
        valid_values = {s.value for s in RunState}

        def _exists(st: str) -> bool:
            return st in valid_names or st.lower() in valid_values

        unknown = [
            f"{f}->{t}"
            for f, t in transitions
            if not _exists(f) or not _exists(t)
        ]
        state_check = {
            "runstate_importable": True,
            "valid_enum_members": len(valid_names),
            "unknown_state_references": unknown,
        }
        if unknown:
            return _emit(
                {
                    "status": "fail",
                    "check": "state_transition_coverage",
                    "reason": f"unknown RunState references: {unknown}",
                    **state_check,
                },
                1,
            )
    except ImportError:
        state_check = {"runstate_importable": False}

    return _emit(
        {
            "status": "pass",
            "check": "state_transition_coverage",
            "transitions_covered": len(transitions),
            "min_required": min_required,
            "test_file": str(MATRIX_TEST.relative_to(ROOT)),
            **state_check,
        },
        0,
    )


if __name__ == "__main__":
    sys.exit(main())
