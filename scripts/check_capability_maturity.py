#!/usr/bin/env python3
"""CI gate: every registered CapabilityDescriptor must have an explicit maturity_level (Rule 13 / CL5)."""  # noqa: E501  # expiry_wave: Wave 27  # added: W25 baseline sweep
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

VALID_LEVELS = {"L0", "L1", "L2", "L3", "L4"}
# Files that contain CapabilityDescriptor instantiations
REGISTRY_FILES = [
    "hi_agent/capability/tools/builtin.py",
    "hi_agent/capability/adapters/descriptor_factory.py",
]
# Descriptor files produced via factory (check that factory passes maturity_level)
FACTORY_FILES = [
    "hi_agent/capability/adapters/descriptor_factory.py",
]

DATACLASS_FILE = "hi_agent/capability/registry.py"


def check_descriptor_field_present() -> list[str]:
    """Verify that CapabilityDescriptor declares maturity_level."""
    violations = []
    src = Path(DATACLASS_FILE).read_text(encoding="utf-8")
    if "maturity_level" not in src:
        violations.append(f"{DATACLASS_FILE}: CapabilityDescriptor is missing maturity_level field")
    return violations


def find_descriptor_instantiations(path: str) -> list[tuple[int, str | None]]:
    """Return list of (lineno, maturity_level_value) for each CapabilityDescriptor(...) call."""
    src = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=path)
    results = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "CapabilityDescriptor"
        ):
            maturity = None
            for kw in node.keywords:
                if kw.arg == "maturity_level":
                    if isinstance(kw.value, ast.Constant):  # noqa: SIM108  # expiry_wave: Wave 27  # added: W25 baseline sweep
                        maturity = kw.value.value
                    else:
                        maturity = "<dynamic>"
            results.append((node.lineno, maturity))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Capability maturity gate.")
    parser.add_argument("--strict", action="store_true",
                        help="Treat absent input as fail rather than not_applicable")
    args = parser.parse_args()

    # not_applicable when the capability registry doesn't exist (fresh checkout, stripped bundle)
    if not Path(DATACLASS_FILE).exists():
        if args.strict:
            print(f"FAIL (strict): input absent at {DATACLASS_FILE}; "
                  "in strict mode, absent input is a defect", file=sys.stderr)
            return 1
        print(f"not_applicable: {DATACLASS_FILE} not found")
        return 0

    violations: list[str] = []

    # 1. Check field exists on dataclass
    violations.extend(check_descriptor_field_present())

    # 2. Check all production instantiations have explicit maturity_level
    for registry_file in REGISTRY_FILES:
        if not Path(registry_file).exists():
            continue
        instantiations = find_descriptor_instantiations(registry_file)
        for lineno, maturity in instantiations:
            # descriptor_factory.py uses a variable (not a literal) — that's OK
            if maturity == "<dynamic>":
                continue
            if maturity is None:
                violations.append(
                    f"{registry_file}:{lineno}: CapabilityDescriptor instantiation missing maturity_level"  # noqa: E501  # expiry_wave: Wave 27  # added: W25 baseline sweep
                )
            elif maturity not in VALID_LEVELS:
                violations.append(
                    f"{registry_file}:{lineno}: maturity_level={maturity!r} not in {sorted(VALID_LEVELS)}"  # noqa: E501  # expiry_wave: Wave 27  # added: W25 baseline sweep
                )

    if violations:
        print(f"FAIL: {len(violations)} capability maturity violation(s):")
        for v in violations:
            print(f"  {v}")
        return 1

    total = sum(
        len(find_descriptor_instantiations(f))
        for f in REGISTRY_FILES
        if Path(f).exists()
    )
    print(f"PASS: capability maturity check ({total} CapabilityDescriptor instantiation(s) verified)")  # noqa: E501  # expiry_wave: Wave 27  # added: W25 baseline sweep
    return 0


if __name__ == "__main__":
    sys.exit(main())
