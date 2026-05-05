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
    # W35-T1 — agent_server frozen contracts. All Rule 12 spine-bearing
    # dataclasses under agent_server/contracts/ now validate spine
    # completeness in __post_init__ via the typed
    # ``SpineCompletenessError`` re-exported from
    # ``agent_server.contracts.errors`` and the local ``_strict_posture``
    # helper (R-AS-1: agent_server must NOT import hi_agent runtime).
    ("agent_server/contracts/run.py", "RunRequest"),
    ("agent_server/contracts/run.py", "RunResponse"),
    ("agent_server/contracts/run.py", "RunStatus"),
    ("agent_server/contracts/run.py", "RunStream"),
    ("agent_server/contracts/tenancy.py", "TenantContext"),
    ("agent_server/contracts/tenancy.py", "TenantQuota"),
    ("agent_server/contracts/tenancy.py", "CostEnvelope"),
    ("agent_server/contracts/skill.py", "SkillRegistration"),
    ("agent_server/contracts/skill.py", "SkillVersion"),
    ("agent_server/contracts/skill.py", "SkillResolution"),
    ("agent_server/contracts/memory.py", "MemoryReadKey"),
    ("agent_server/contracts/memory.py", "MemoryWriteRequest"),
    ("agent_server/contracts/streaming.py", "Event"),
    ("agent_server/contracts/streaming.py", "EventCursor"),
    ("agent_server/contracts/streaming.py", "EventFilter"),
    ("agent_server/contracts/llm_proxy.py", "LLMRequest"),
    ("agent_server/contracts/llm_proxy.py", "LLMResponse"),
    ("agent_server/contracts/gate.py", "PauseToken"),
    ("agent_server/contracts/gate.py", "ResumeRequest"),
    ("agent_server/contracts/gate.py", "GateEvent"),
    ("agent_server/contracts/workspace.py", "BlobRef"),
    ("agent_server/contracts/workspace.py", "WorkspaceObject"),
    # W35-T1 — hi_agent contracts spine backfill (HIGH). Every request /
    # response dataclass that flows across the runtime adapter or the
    # persistence boundary now carries a posture-aware __post_init__:
    # research/prod raises SpineCompletenessError, dev logs a warning.
    # Mirrors the W34-F.3 ReasoningTrace canonical pattern.
    ("hi_agent/contracts/reasoning_trace.py", "ReasoningTraceEntry"),
    ("hi_agent/contracts/reasoning_trace.py", "ReasoningTrace"),
    ("hi_agent/contracts/requests.py", "StartRunRequest"),
    ("hi_agent/contracts/requests.py", "StartRunResponse"),
    ("hi_agent/contracts/requests.py", "SignalRunRequest"),
    ("hi_agent/contracts/requests.py", "QueryRunResponse"),
    ("hi_agent/contracts/requests.py", "TraceRuntimeView"),
    ("hi_agent/contracts/requests.py", "OpenBranchRequest"),
    ("hi_agent/contracts/requests.py", "BranchStateUpdateRequest"),
    ("hi_agent/contracts/requests.py", "HumanGateRequest"),
    ("hi_agent/contracts/requests.py", "ApprovalRequest"),
    ("hi_agent/contracts/requests.py", "KernelManifest"),
    ("hi_agent/contracts/requests.py", "RunResult"),
    ("hi_agent/contracts/team_runtime.py", "TeamRun"),
    ("hi_agent/contracts/task.py", "TaskContract"),
    # W35-T2 — gate-decision WEAK_PARITY closure (HIGH). Was strict-only
    # raise; now also logs a structured warning under dev posture so the
    # observability surface matches the rest of the spine-bearing set.
    ("hi_agent/contracts/gate_decision.py", "GateDecisionRequest"),
    # W35-T1 — hi_agent server-side persistent records. All four are
    # durable spine-bearing dataclasses; backfill mirrors W34's RunRecord
    # / StoredEvent pattern.
    ("hi_agent/server/idempotency.py", "IdempotencyRecord"),
    ("hi_agent/server/session_store.py", "SessionRecord"),
    ("hi_agent/server/team_event_store.py", "TeamEvent"),
    ("hi_agent/server/tenant_context.py", "TenantContext"),
    # W35-T1/T2 — evolve / skill / artifacts / memory / operations spine
    # backfill. Each carries a posture-aware __post_init__ that raises
    # SpineCompletenessError (or ValueError) under research/prod when
    # required spine fields are empty; dev posture logs a warning.
    ("hi_agent/evolve/contracts.py", "EvolveMetrics"),
    ("hi_agent/evolve/contracts.py", "EvolveResult"),
    ("hi_agent/evolve/feedback_store.py", "RunFeedback"),
    ("hi_agent/skill/observer.py", "SkillObservation"),
    ("hi_agent/artifacts/contracts.py", "Artifact"),
    ("hi_agent/memory/episodic.py", "EpisodeRecord"),
    ("hi_agent/operations/op_store.py", "OpHandle"),
)


def _module_helpers_with_spine_check(tree: ast.AST) -> set[str]:
    """Return module-level helper function names that themselves implement
    the posture-aware spine-validation pattern.

    A helper qualifies when its body references ``Posture`` + a spine field
    name + raises (or names ``SpineCompletenessError``). This lets dataclasses
    that delegate to a shared validator (e.g. ``_validate_spine`` /
    ``_validate_tenant_id`` in ``hi_agent/contracts/requests.py``) be
    recognised by the gate without forcing the body to inline the same
    pattern eleven times.
    """
    helpers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("_"):
            continue
        src = ast.unparse(node)
        has_posture = "Posture" in src or "posture" in src
        has_raise = "raise" in src or "SpineCompletenessError" in src
        # A helper need not name a specific spine field literally — its job
        # is to take the field/value mapping from the caller. The caller's
        # ``__post_init__`` is what asserts the spine-field reference.
        if has_posture and has_raise:
            helpers.add(node.name)
    return helpers


def _has_post_init_with_spine_check(
    class_node: ast.ClassDef,
    module_helpers: set[str],
) -> tuple[bool, str]:
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
    #
    # Helper-delegation case: when ``__post_init__`` calls a module-level
    # helper that itself satisfies the pattern (e.g. ``_validate_spine``),
    # the inline body may not reference Posture/raise directly. We accept
    # the delegation as long as such a helper is invoked AND the call site
    # references at least one spine field name.
    src = ast.unparse(post_init)
    has_posture = "Posture" in src or "posture" in src
    has_spine_ref = any(
        field in src for field in ("tenant_id", "run_id", "stage_id", "parent_run_id", "attempt_id", "phase_id")
    )
    has_raise = "raise" in src or "SpineCompletenessError" in src

    delegates_to_helper = False
    for call in ast.walk(post_init):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            if call.func.id in module_helpers:
                delegates_to_helper = True
                break

    if delegates_to_helper and has_spine_ref:
        return True, ""

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
        module_helpers = _module_helpers_with_spine_check(tree)
        class_node: ast.ClassDef | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                class_node = node
                break
        if class_node is None:
            failures.append(f"{rel_path}: class {class_name} not found")
            continue
        ok, reason = _has_post_init_with_spine_check(class_node, module_helpers)
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
