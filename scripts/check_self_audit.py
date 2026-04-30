#!/usr/bin/env python3
"""Rule 9 enforcement — ship-blocking categories must have no open findings in latest notice."""
import glob
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NOTICE_GLOB = str(REPO / "docs" / "downstream-responses" / "*.md")

SHIP_BLOCKING_CATEGORIES = [
    "LLM path", "Run lifecycle", "HTTP contract",
    "Security boundary", "Resource lifetime", "Observability",
]

OPEN_ITEM_RE = re.compile(r"^\s*-\s*\[\s*\]", re.MULTILINE)
STATUS_RE = re.compile(r"Status:\s*(SHIP|KNOWN-DEFECT-NOTICE|DRAFT)", re.IGNORECASE)
DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def main() -> None:
    as_json = "--json" in sys.argv

    notices = sorted(
        [p for p in glob.glob(NOTICE_GLOB) if DATE_PREFIX_RE.search(Path(p).name)],
        reverse=True,
    )
    if not notices:
        result = {"check": "self_audit", "status": "pass", "reason": "no_notices_found"}
        print(json.dumps(result) if as_json else "PASS: no delivery notices found")
        sys.exit(0)

    latest = Path(notices[0])
    content = latest.read_text(encoding="utf-8")

    open_items: list[str] = []
    for line in content.splitlines():
        if OPEN_ITEM_RE.match(line):
            for cat in SHIP_BLOCKING_CATEGORIES:
                if cat.lower() in line.lower():
                    open_items.append(line.strip())

    status_match = STATUS_RE.search(content)
    has_status = bool(status_match)

    violations = []
    if open_items:
        violations.append({"type": "open_ship_blocking_findings", "items": open_items})
    if not has_status:
        violations.append({"type": "missing_status_field", "notice": latest.name})

    status = "fail" if violations else "pass"
    result = {
        "check": "self_audit", "status": status,
        "latest_notice": latest.name,
        "violations": violations,
    }
    if as_json:
        print(json.dumps(result, indent=2))
    elif violations:
        for v in violations:
            print(f"SELF-AUDIT FAIL: {v}", file=sys.stderr)
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
