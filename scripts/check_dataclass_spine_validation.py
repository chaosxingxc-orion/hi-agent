#!/usr/bin/env python3
"""W34-F.3 / B-W34-2 dataclass-spine-validation gate.

Walks production dataclass definitions that carry the Rule 12 spine fields
(``tenant_id`` plus ``run_id`` / ``stage_id`` / ``parent_run_id`` /
``attempt_id`` / ``phase_id``) and asserts each has a ``__post_init__`` that
validates spine completeness under research/prod posture.

Today's enforced set:
- ``hi_agent/contracts/reasoning.py::ReasoningTrace`` — closed in W34-F.3.

Add new entries to ``REQUIRED_VALIDATION_TARGETS`` when a new spine-bearing
dataclass joins the platform.

Exit 0 if every required target carries the validation; exit 1 with a list
of missing targets otherwise.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_VALIDATION_TARGETS: tuple[tuple[str, str], ...] = (
    ("hi_agent/contracts/reasoning.py", "ReasoningTrace"),
    # W34+ T2a — durable trio. RunRecord / StoredEvent are persisted
    # and ManagedRun is the in-memory shape consumed by every emit path;
    # all three now carry posture-aware __post_init__ that fails closed
    # under research/prod when run_id / tenant_id (and event_id for
    # StoredEvent) are empty. Mirrors the W34-F.3 ReasoningTrace pattern.
    ("hi_agent/server/run_store.py", "RunRecord"),
    ("hi_agent/server/event_store.py", "StoredEvent"),
    ("hi_agent/server/run_manager.py", "ManagedRun"),
)


def _has_post_init_with_spine_check(class_node: ast.ClassDef) -> tuple[bool, str]:
    """Return (has_post_init, reason)."""
    post_init: ast.FunctionDef | None = None
    for item in class_node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "__post_init__":
            post_init = item
            break
    if post_init is None:
        return False, "no __post_init__ defined"

    # Heuristic: the body must reference Posture (or the spine-completeness
    # error type) AND must reference at least one spine field name. We do not
    # try to type-check the implementation; the gate's job is to ensure a
    # validation hook exists, the unit test covers the actual semantics.
    src = ast.unparse(post_init)
    has_posture = "Posture" in src or "posture" in src
    has_spine_ref = any(
        field in src for field in ("tenant_id", "run_id", "stage_id", "parent_run_id", "attempt_id", "phase_id")
    )
    has_raise = "raise" in src or "SpineCompletenessError" in src
    if not (has_posture and has_spine_ref and has_raise):
        return False, (
            "__post_init__ does not reference Posture + spine fields + raise; "
            "the validation must fail-closed under research/prod posture"
        )
    return True, ""


def main() -> int:
    failures: list[str] = []
    for rel_path, class_name in REQUIRED_VALIDATION_TARGETS:
        path = ROOT / rel_path
        if not path.exists():
            failures.append(f"{rel_path}: file not found")
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{rel_path}: parse error: {exc}")
            continue
        class_node: ast.ClassDef | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                class_node = node
                break
        if class_node is None:
            failures.append(f"{rel_path}: class {class_name} not found")
            continue
        ok, reason = _has_post_init_with_spine_check(class_node)
        if not ok:
            failures.append(f"{rel_path}::{class_name}: {reason}")

    if failures:
        print("FAIL dataclass_spine_validation:")
        for f in failures:
            print(f"  {f}")
        print(
            "\n  Each spine-bearing dataclass must define __post_init__ that "
            "raises under research/prod posture when a required spine field "
            "is empty. See hi_agent/contracts/reasoning.py::ReasoningTrace "
            "for the canonical pattern."
        )
        return 1
    print(
        f"OK dataclass_spine_validation ({len(REQUIRED_VALIDATION_TARGETS)} targets, all carry __post_init__)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
