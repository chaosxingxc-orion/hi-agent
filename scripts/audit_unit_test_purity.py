"""Audit tests/unit/*.py for real network calls without mocking.

Reports tests that import or call LLM gateway functions without respx.mock or mocker.patch.
Exits 0 if clean, 1 if suspicious patterns found.

Usage: python scripts/audit_unit_test_purity.py [--strict]
"""

import argparse
import re
import sys
from pathlib import Path

SUSPICIOUS_PATTERNS = [
    r"anthropic_gateway",
    r"volces_gateway",
    r"_create_gateway",
    r"httpx\.AsyncClient\(",
    r"requests\.get\(",
    r"requests\.post\(",
]
MOCK_INDICATORS = [
    "respx.mock",
    "mocker.patch",
    "unittest.mock",
    "@pytest.mark.external_llm",
    "@pytest.mark.live_api",
    "@pytest.mark.network",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit tests/unit/*.py for unguarded live network calls."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit 1 even on warnings (same as default; reserved for future use).",
    )
    args = parser.parse_args()
    _ = args.strict  # currently no difference; placeholder for future tiers

    unit_dir = Path("tests/unit")
    if not unit_dir.is_dir():
        # Try relative to repo root
        repo_root = Path(__file__).resolve().parent.parent
        unit_dir = repo_root / "tests" / "unit"

    findings = []
    for f in sorted(unit_dir.glob("*.py")):
        content = f.read_text(encoding="utf-8")
        for pattern in SUSPICIOUS_PATTERNS:
            if re.search(pattern, content):
                # Check if file has mock indicators
                has_mock = any(ind in content for ind in MOCK_INDICATORS)
                if not has_mock:
                    findings.append(
                        f"{f}: suspicious pattern '{pattern}' without mock indicator"
                    )

    if findings:
        print("AUDIT FAIL — live network calls without mock markers:")
        for finding in findings:
            print(f"  {finding}")
        return 1

    print("AUDIT OK — no unguarded live network calls in tests/unit/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
