"""``agent-server run`` — submit a run via the northbound facade (W24 I-E).

Reads a JSON file containing the run-request body, posts it to the
configured server, and prints the response. Stdlib only; no imports
from hi_agent.* per R-AS-1.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]  # expiry_wave: Wave 30
    parser = subparsers.add_parser(
        "run",
        help="POST a run request to /v1/runs.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--tenant", required=True, help="Tenant id (X-Tenant-Id header).")
    parser.add_argument(
        "--request-json",
        required=True,
        help="Path to a JSON file with the request body.",
    )
    parser.add_argument(
        "--idempotency-key",
        default="",
        help=(
            "Optional explicit Idempotency-Key header. If omitted, the "
            "value of body.idempotency_key is used."
        ),
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    try:
        with open(args.request_json, encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: cannot load request JSON: {exc}", file=sys.stderr)
        return 2

    if not isinstance(body, dict):
        print("Error: request JSON must decode to a JSON object.", file=sys.stderr)
        return 2

    idem_key = args.idempotency_key or str(body.get("idempotency_key", ""))
    headers = {
        "Content-Type": "application/json",
        "X-Tenant-Id": args.tenant,
    }
    if idem_key:
        headers["Idempotency-Key"] = idem_key

    url = args.server.rstrip("/") + "/v1/runs"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    opener = _build_opener(args.server)
    try:
        with opener.open(request, timeout=args.timeout) as resp:
            payload = resp.read().decode("utf-8")
            print(payload)
            return 0
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {body_text}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"connection_failed: {exc.reason}", file=sys.stderr)
        return 1


def _build_opener(server: str) -> urllib.request.OpenerDirector:
    """Build an opener that bypasses HTTP(S)_PROXY for localhost servers."""
    if "127.0.0.1" in server or "localhost" in server:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()
