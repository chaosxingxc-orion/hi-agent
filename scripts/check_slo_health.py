#!/usr/bin/env python3
"""CI gate: verify that all four /ops/ management routes are registered in app.py.

Checks for presence of:
  /ops/slo
  /ops/alerts
  /ops/runbook
  /ops/dashboard

Exits 0 when all four are present; exits 1 with details otherwise.
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
APP_PY = ROOT / "hi_agent" / "server" / "app.py"

REQUIRED_ROUTES = [
    "/ops/slo",
    "/ops/alerts",
    "/ops/runbook",
    "/ops/dashboard",
]


def check_routes(app_src: str) -> list[str]:
    """Return list of missing route strings."""
    return [route for route in REQUIRED_ROUTES if route not in app_src]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    if not APP_PY.exists():
        msg = f"app.py not found at {APP_PY}"
        if args.json:
            print(json.dumps({"status": "fail", "error": msg}))
        else:
            print(f"FAIL check_slo_health: {msg}")
        return 1

    app_src = APP_PY.read_text(encoding="utf-8")
    missing = check_routes(app_src)

    if args.json:
        if missing:
            print(json.dumps({"status": "fail", "missing_routes": missing}))
        else:
            print(json.dumps({"status": "pass"}))
    else:
        if missing:
            print("FAIL check_slo_health: missing /ops/ routes in app.py:")
            for route in missing:
                print(f"  {route}")
        else:
            print("OK check_slo_health")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

