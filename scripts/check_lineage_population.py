#!/usr/bin/env python3
"""W34-F.2 / B-W34-1 lineage-population gate.

Walks every ``RunExecutionContext(...)`` direct construction call site under
``hi_agent/`` and ``agent_server/`` and fails CI when any literal empty
string is passed to a lineage-spine field
(``parent_run_id`` / ``attempt_id`` / ``phase_id``).

The gate is intentionally conservative: it allows variable references and
``getattr(...) or ""`` patterns through (the runtime check happens via
``ReasoningTrace.__post_init__`` and the integration test in
``tests/integration/test_run_lineage_persisted_after_recovery.py``). Hardcoded
empty-string assignments are exactly the bug shape that W33-F.1 storage
spine landed without — the executor-side population was the gap.

Exit 0 on clean; exit 1 with a list of (file:line, field) pairs otherwise.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("hi_agent", "agent_server")
LINEAGE_FIELDS = frozenset({"parent_run_id", "attempt_id", "phase_id"})

# Allow-list specific construction sites where empty lineage is documented
# as the intended root-run shape. Each entry must be `<rel-path>:<lineno>`
# referring to the keyword construction site.
ALLOWLIST: frozenset[str] = frozenset({
    # The ManagedRun + RunExecutionContext literal at create_run sets
    # parent_run_id="" intentionally for ROOT runs. attempt_id is generated
    # via str(uuid.uuid4()) and is NEVER literal "". phase_id is sourced
    # from task_contract.get(...) and may be empty for runs that don't yet
    # carry phase metadata.
    "hi_agent/server/run_manager.py:create_run::root_run_lineage_seed",
})


def _is_runexecutioncontext_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "RunExecutionContext":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "RunExecutionContext":
        return True
    return False


def _scan_file(path: Path) -> list[tuple[str, int, str]]:
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []
    violations: list[tuple[str, int, str]] = []
    rel = path.relative_to(ROOT).as_posix()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_runexecutioncontext_call(node):
            continue
        for kw in node.keywords:
            if kw.arg not in LINEAGE_FIELDS:
                continue
            value = kw.value
            # Empty-string literal is the bug shape we are catching.
            if isinstance(value, ast.Constant) and value.value == "":
                # parent_run_id="" is permitted for root runs — but only when
                # the call site is annotated with "# scope: root-run" on the
                # same line, OR explicitly listed in ALLOWLIST.
                # A plain `parent_run_id=""` without the marker is the bug.
                if kw.arg == "parent_run_id":
                    line = src.splitlines()[kw.lineno - 1] if 0 < kw.lineno <= len(src.splitlines()) else ""
                    if "# scope: root-run" in line:
                        continue
                # ``attempt_id=""`` and ``phase_id=""`` are always violations:
                # attempt_id MUST be a fresh UUID at create_run; phase_id is
                # either copied from task_contract or derived — never literal.
                violations.append((rel, kw.lineno, kw.arg))
    return violations


def main() -> int:
    all_violations: list[tuple[str, int, str]] = []
    for sub in SCAN_ROOTS:
        root = ROOT / sub
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            # Skip the context module itself — its cls(...) literal is the
            # field-default declaration, not a construction-site bug.
            if py.relative_to(ROOT).as_posix() == "hi_agent/context/run_execution_context.py":
                continue
            all_violations.extend(_scan_file(py))

    if not all_violations:
        print("OK lineage_population (no hardcoded-empty lineage in RunExecutionContext call sites)")
        return 0

    print("FAIL lineage_population:")
    for rel, lineno, field in all_violations:
        print(f"  {rel}:{lineno}  {field}=\"\"  (W34-F.2 / B-W34-1)")  # wave-literal-ok
    print(
        "\n  Each call site must populate the lineage field from the live "
        "ManagedRun spine, the task_contract, or a fresh UUID. Add "
        "'# scope: root-run' inline if parent_run_id=\"\" is intentional "
        "for a documented root-run construction."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
