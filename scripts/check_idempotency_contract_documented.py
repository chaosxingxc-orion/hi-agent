#!/usr/bin/env python
"""CI gate: verify ``agent_server/contracts/idempotency.py`` carries the
binding spec documentation for the v1 idempotency contract (W34-D).

Asserts:
  1. The module file exists.
  2. The module docstring contains all four sub-headers required by
     the W34 plan: ``Cache Scope``, ``Cross-Process Replay``, ``TTL``,
     ``Body-Mismatch Behaviour``.
  3. ``DEFAULT_TTL_SECONDS`` is defined and is a positive number.

Exit 0 = PASS; 1 = FAIL.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACT_FILE = ROOT / "agent_server" / "contracts" / "idempotency.py"

REQUIRED_SUBHEADERS: tuple[str, ...] = (
    "Cache Scope",
    "Cross-Process Replay",
    "TTL",
    "Body-Mismatch Behaviour",
)


def _read_module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _module_docstring(tree: ast.Module) -> str | None:
    return ast.get_docstring(tree)


def _module_constant(tree: ast.Module, name: str) -> object | None:
    """Return the literal value of a top-level assignment ``name``.

    Supports plain ``Assign`` and ``AnnAssign`` forms with a
    ``Constant`` RHS (numbers, strings). Returns ``None`` when the
    assignment is missing or non-literal.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == name
                    and isinstance(node.value, ast.Constant)
                ):
                    return node.value.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and isinstance(node.value, ast.Constant)
        ):
            return node.value.value
    return None


def main() -> int:
    violations: list[str] = []

    if not CONTRACT_FILE.exists():
        print(
            f"FAIL: {CONTRACT_FILE.relative_to(ROOT)} does not exist; "
            "create the W34-D idempotency contract module first."  # wave-literal-ok
        )
        return 1

    try:
        tree = _read_module_ast(CONTRACT_FILE)
    except SyntaxError as exc:
        print(f"FAIL: cannot parse {CONTRACT_FILE.relative_to(ROOT)}: {exc}")
        return 1

    docstring = _module_docstring(tree)
    if not docstring:
        violations.append(
            "module-level docstring is missing — the contract module "
            "must carry the binding spec text"
        )
    else:
        for header in REQUIRED_SUBHEADERS:
            # Match either '## Cache Scope' Markdown form or any header
            # form that contains the literal phrase. The plan calls for
            # `## Cache Scope` etc., but stay lenient about leading hashes.
            if header not in docstring:
                violations.append(
                    f'docstring missing required sub-header: "{header}"'
                )

    ttl_value = _module_constant(tree, "DEFAULT_TTL_SECONDS")
    if ttl_value is None:
        violations.append(
            "DEFAULT_TTL_SECONDS is not defined as a top-level "
            "literal assignment"
        )
    elif not isinstance(ttl_value, (int, float)) or isinstance(ttl_value, bool):
        violations.append(
            f"DEFAULT_TTL_SECONDS must be a number, got "
            f"{type(ttl_value).__name__}"
        )
    elif ttl_value <= 0:
        violations.append(
            f"DEFAULT_TTL_SECONDS must be positive, got {ttl_value!r}"
        )

    if violations:
        print("FAIL idempotency_contract_documented:")
        for v in violations:
            print(f"  - {v}")
        return 1

    print("OK idempotency_contract_documented")
    return 0


if __name__ == "__main__":
    sys.exit(main())
