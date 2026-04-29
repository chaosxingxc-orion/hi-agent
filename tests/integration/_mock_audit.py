"""AST-based audit: detect SUT-internal mocks in integration tests (AX-B B1).

Called by check_test_honesty.py. Returns list of violations where
integration tests mock classes/modules from SUT internals.

FALSE POSITIVES to skip (documented at scan time):
- urllib.request.urlopen patches => OS/network boundary (OK)
- external backend MagicMock in test_long_running_op.py => boundary mock (documented)
- asyncio.Task MagicMock in test_dispatch_subrun_error_callback.py => boundary mock (OK)
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# SUT modules that should NOT be mocked in integration tests.
# Boundary mocks of network/file/OS are OK and are NOT flagged here.
SUT_MODULES = {
    "hi_agent.server",
    "hi_agent.execution",
    "hi_agent.llm",
    "hi_agent.knowledge",
    "hi_agent.memory",
    "hi_agent.artifacts",
    "hi_agent.management",
    "hi_agent.evolve",
    "hi_agent.capability",
    "hi_agent.task_mgmt",
    "hi_agent.context",
    "hi_agent.config",
    "hi_agent.runner",
    "hi_agent.runtime",
    "hi_agent.runtime_adapter",
}

# Files confirmed as FALSE POSITIVES — boundary mocks only, no SUT mocking.
# See annotation comments in each file for rationale.
_FALSE_POSITIVE_FILES = {
    # urllib.request.urlopen is OS-level network boundary.
    "tests/integration/test_kernel_facade_client.py",
    # External job-scheduling backend — documented boundary mock.
    "tests/integration/test_long_running_op.py",
    # asyncio.Task is stdlib boundary, not SUT.
    "tests/integration/test_dispatch_subrun_error_callback.py",
    # os.replace is OS-level file-system boundary.
    "tests/integration/test_run_state_atomic_write.py",
    # gateway._client.post is HTTP client boundary.
    "tests/integration/test_async_llm_integration.py",
    # urllib.request.urlopen and httpx.Client.post are network boundaries (P3 compliant).
    "tests/integration/test_real_executor_e2e.py",
}


# Suffixes that indicate the patch target is a stdlib/boundary seam accessed
# through the SUT namespace — e.g. "hi_agent.llm.http_gateway.urllib.request.urlopen".
# These are legitimate transport-layer patches, NOT SUT-internal mocks.
_BOUNDARY_SUFFIXES = {
    # stdlib network
    "urllib.request.urlopen",
    "urllib.request.Request",
    # time / randomness
    "time.sleep",
    "time.monotonic",
    "time.time",
    "random.uniform",
    "random.random",
    # os
    "os.replace",
    "os.getenv",
    "os.environ",
}


def _is_sut_target(s: str) -> bool:
    """Return True if the string looks like a SUT-internal module/class path.

    Returns False when the target is a stdlib boundary accessed through the
    SUT namespace (e.g., "hi_agent.llm.X.urllib.request.urlopen").
    """
    if not any(s.startswith(m) for m in SUT_MODULES):
        return False
    # Filter out stdlib boundary seams patched through SUT namespace.
    return all(not s.endswith(suffix) for suffix in _BOUNDARY_SUFFIXES)


def _normalise_path(path: Path) -> str:
    """Return a forward-slash relative path for cross-platform comparison."""
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return str(path).replace("\\", "/")
    return str(rel).replace("\\", "/")


def scan_file(path: Path) -> list[dict]:
    """Return list of SUT-internal mock violations in the given test file.

    Detects:
    - @patch("hi_agent.X.Y") decorator / context-manager with a SUT string arg
    - patch.object(<SUT class/module>, ...) calls
    - monkeypatch.setattr targeting a SUT module attribute

    Does NOT flag:
    - Boundary mocks (urllib, os, asyncio) — see _FALSE_POSITIVE_FILES
    - Direct attribute assignment (executor._foo = bar) — tracked separately
      via expiry_wave comments in the source files
    """
    norm_path = _normalise_path(path)
    if norm_path in _FALSE_POSITIVE_FILES:
        return []

    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except (OSError, SyntaxError):
        return []

    violations: list[dict] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""

        # ----------------------------------------------------------------
        # Pattern 1: patch("hi_agent.X") or patch.object(...) with string
        # ----------------------------------------------------------------
        if "patch" in func_str:
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and _is_sut_target(arg.value)
                ):
                    violations.append(
                            {
                                "file": norm_path,
                                "line": node.lineno,
                                "target": arg.value,
                                "kind": "sut_patch_string",
                                "description": (
                                    f"B1: patch targets SUT-internal module '{arg.value}'"
                                ),
                            }
                        )

        # ----------------------------------------------------------------
        # Pattern 2: monkeypatch.setattr(sut_module, ...)
        # ----------------------------------------------------------------
        is_setattr = func_str.endswith("setattr") or func_str == "monkeypatch.setattr"
        if is_setattr and len(node.args) >= 2:
            first = node.args[0]
            # Try to detect setattr(sut_var, "method", ...) where
            # sut_var is an attribute/name that could be a SUT import.
            if isinstance(first, ast.Attribute) and len(node.args) >= 3:
                # e.g. monkeypatch.setattr(_l0_mod.L0Summarizer, "summarize_run", ...)
                owner = ast.unparse(first) if hasattr(ast, "unparse") else ""
                second = node.args[1]
                if isinstance(second, ast.Constant) and isinstance(second.value, str):
                    # Heuristic: flag setattr on attribute objects; callers that are
                    # genuine boundary mocks are listed in _FALSE_POSITIVE_FILES.
                    violations.append(
                        {
                            "file": norm_path,
                            "line": node.lineno,
                            "target": f"{owner}.{second.value}",
                            "kind": "sut_monkeypatch_setattr",
                            "description": (
                                f"B1: monkeypatch.setattr on "
                                f"'{owner}.{second.value}' — verify not SUT-internal"
                            ),
                        }
                    )

    return violations


def scan_directory(directory: Path) -> list[dict]:
    """Scan all .py files under *directory* and return combined violations."""
    violations: list[dict] = []
    for py_file in sorted(directory.rglob("*.py")):
        violations.extend(scan_file(py_file))
    return violations
