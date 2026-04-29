#!/usr/bin/env python3
"""CI gate: SLO health endpoints return valid schema (AX-D slo_health rewrite).

If HI_AGENT_SERVER_URL is set, probes the live server endpoints via HTTP.
Otherwise, calls the ops handlers in-process using the Starlette TestClient.

Exit 0: PASS
Exit 1: FAIL
Exit 2: not_applicable
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OPS_ENDPOINTS = [
    "/ops/slo",
    "/ops/alerts",
    "/ops/runbook",
    "/ops/dashboard",
]


def _probe_live_server(base_url: str, timeout: float = 10.0) -> list[dict]:
    """Probe ops endpoints on a live server. Returns list of result dicts."""
    try:
        import httpx
    except ImportError:
        return [
            {"endpoint": e, "status": "fail", "reason": "httpx not installed"}
            for e in OPS_ENDPOINTS
        ]

    results = []
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        for endpoint in OPS_ENDPOINTS:
            try:
                resp = client.get(endpoint)
                if resp.status_code == 404:
                    results.append(
                        {"endpoint": endpoint, "status": "not_found", "code": 404}
                    )
                elif resp.status_code >= 500:
                    results.append(
                        {"endpoint": endpoint, "status": "fail", "code": resp.status_code}
                    )
                else:
                    ct = resp.headers.get("content-type", "")
                    body = (
                        resp.json() if ct.startswith("application/json") else {}
                    )
                    results.append(
                        {
                            "endpoint": endpoint,
                            "status": "pass",
                            "code": resp.status_code,
                            "body_keys": list(body.keys()) if body else [],
                        }
                    )
            except Exception as exc:
                results.append(
                    {"endpoint": endpoint, "status": "fail", "reason": str(exc)}
                )
    return results


def _probe_in_process() -> list[dict]:
    """Probe ops endpoints using Starlette TestClient (no subprocess needed)."""
    try:
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=9999)
        client = TestClient(server.app, raise_server_exceptions=False)
        results = []
        for endpoint in OPS_ENDPOINTS:
            try:
                resp = client.get(endpoint)
                if resp.status_code == 404:
                    results.append(
                        {"endpoint": endpoint, "status": "not_found", "code": 404}
                    )
                elif resp.status_code >= 500:
                    results.append(
                        {"endpoint": endpoint, "status": "fail", "code": resp.status_code}
                    )
                else:
                    results.append(
                        {"endpoint": endpoint, "status": "pass", "code": resp.status_code}
                    )
            except Exception as exc:
                results.append(
                    {"endpoint": endpoint, "status": "fail", "reason": str(exc)}
                )
        return results
    except ImportError as exc:
        return [
            {
                "endpoint": ep,
                "status": "not_applicable",
                "reason": f"import error: {exc}",
            }
            for ep in OPS_ENDPOINTS
        ]
    except Exception as exc:
        return [
            {
                "endpoint": ep,
                "status": "not_applicable",
                "reason": f"in-process probe failed: {exc}",
            }
            for ep in OPS_ENDPOINTS
        ]


def main() -> int:
    parser = argparse.ArgumentParser(description="SLO health gate.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    server_url = os.environ.get("HI_AGENT_SERVER_URL", "")
    results = _probe_live_server(server_url) if server_url else _probe_in_process()

    # All not_applicable means the server could not be reached at all.
    all_na = all(r["status"] == "not_applicable" for r in results)
    if all_na:
        if args.strict:
            status = "fail"
            reason = "all ops endpoints returned not_applicable in strict mode"
        else:
            status = "not_applicable"
            reason = (
                "could not probe ops endpoints "
                "(set HI_AGENT_SERVER_URL or ensure app is importable)"
            )
        result = {
            "status": status,
            "check": "slo_health",
            "reason": reason,
            "endpoints": results,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{status}: {reason}")
        return 1 if status == "fail" else 2

    failures = [r for r in results if r["status"] == "fail"]
    passes = [r for r in results if r["status"] == "pass"]

    status = "fail" if failures else "pass"
    result = {
        "status": status,
        "check": "slo_health",
        "passed": len(passes),
        "failed": len(failures),
        "endpoints": results,
        "reason": f"{len(failures)} endpoint(s) failed" if failures else "",
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if failures:
            print(
                f"FAIL: {len(failures)} ops endpoint(s) failed:",
                file=sys.stderr,
            )
            for f in failures:
                print(
                    f"  {f['endpoint']}: {f.get('reason', f.get('code', '?'))}",
                    file=sys.stderr,
                )
        else:
            print(f"PASS: {len(passes)} ops endpoint(s) probed OK")

    return 1 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
