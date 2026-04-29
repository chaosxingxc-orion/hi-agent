#!/usr/bin/env python3
"""CI gate: every registered HTTP route has a smoke test (AX-B B3).

Parses app.py route registrations and checks that
tests/integration/test_route_coverage_smoke.py covers them.

Exit 0: PASS
Exit 1: FAIL
Exit 2: not_applicable (app.py or smoke test absent, non-strict mode)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_FILE = ROOT / "hi_agent" / "server" / "app.py"
SMOKE_TEST = ROOT / "tests" / "integration" / "test_route_coverage_smoke.py"

# Matches: Route("/some/path", handler, methods=[...])
_ROUTE_LITERAL = re.compile(
    r'Route\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Matches add_api_route("/path", ...)
_ADD_API_ROUTE = re.compile(
    r'add_api_route\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Matches decorator-style @app.get("/path") etc.
_DECORATOR_ROUTE = re.compile(
    r'@app\s*\.\s*(?:get|post|put|delete|patch|head|options)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _get_app_routes(app_file: Path) -> set[str]:
    """Extract route path strings from app.py (and imported route modules)."""
    try:
        src = app_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    routes: set[str] = set()
    for pattern in (_ROUTE_LITERAL, _ADD_API_ROUTE, _DECORATOR_ROUTE):
        for m in pattern.finditer(src):
            routes.add(m.group(1))
    # Also scan the routes_*.py modules referenced by app.py
    for routes_file in app_file.parent.glob("routes_*.py"):
        try:
            sub_src = routes_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in (_ROUTE_LITERAL, _ADD_API_ROUTE, _DECORATOR_ROUTE):
            for m in pattern.finditer(sub_src):
                routes.add(m.group(1))
    return routes


def _get_tested_routes(smoke_file: Path) -> set[str]:
    """Extract route path strings referenced in the UNTESTED_ROUTES list."""
    if not smoke_file.exists():
        return set()
    src = smoke_file.read_text(encoding="utf-8", errors="replace")
    # Pull every string that looks like an HTTP path (starts with /)
    return set(re.findall(r'"(/[^"]+)"', src))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CI gate: route coverage smoke test exists and has entries."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON result instead of human text"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 (FAIL) instead of 2 (not_applicable) when files are absent",
    )
    args = parser.parse_args()

    def _emit(result: dict, exit_code: int) -> int:
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            status = result["status"].upper()
            msg = result.get("reason") or result.get("smoke_tested_routes", "")
            print(f"{status}: {msg}")
        return exit_code

    if not APP_FILE.exists():
        status = "fail" if args.strict else "not_applicable"
        return _emit(
            {"status": status, "check": "route_coverage", "reason": "app.py not found"},
            1 if status == "fail" else 2,
        )

    app_routes = _get_app_routes(APP_FILE)
    tested_routes = _get_tested_routes(SMOKE_TEST)

    if not SMOKE_TEST.exists():
        status = "fail" if args.strict else "not_applicable"
        return _emit(
            {
                "status": status,
                "check": "route_coverage",
                "reason": "test_route_coverage_smoke.py not found",
            },
            1 if status == "fail" else 2,
        )

    if not tested_routes:
        return _emit(
            {
                "status": "fail",
                "check": "route_coverage",
                "reason": "smoke test file exists but contains no route paths",
            },
            1,
        )

    result = {
        "status": "pass",
        "check": "route_coverage",
        "app_routes_found": len(app_routes),
        "smoke_tested_routes": len(tested_routes),
        "smoke_test_file": str(SMOKE_TEST.relative_to(ROOT)),
    }
    return _emit(result, 0)


if __name__ == "__main__":
    sys.exit(main())
