"""``agent-server cancel`` — cancel a live run (W24 I-E).

The northbound facade currently exposes ``POST /v1/runs/{run_id}/signal``
with ``signal=cancel`` semantics; once Track I-routes lands a dedicated
``/cancel`` endpoint we will switch over. The CLI tries ``/cancel``
first and falls back to the signal endpoint so it works against either
contract version.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]  # expiry_wave: Wave 27
    parser = subparsers.add_parser(
        "cancel",
        help="Cancel a run via /v1/runs/{id}/cancel (or /signal fallback).",
    )
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--idempotency-key",
        default="",
        help="Optional Idempotency-Key header for replay-safe cancellation.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    headers = {
        "Content-Type": "application/json",
        "X-Tenant-Id": args.tenant,
    }
    if args.idempotency_key:
        headers["Idempotency-Key"] = args.idempotency_key

    base = args.server.rstrip("/")
    cancel_url = f"{base}/v1/runs/{args.run_id}/cancel"
    signal_url = f"{base}/v1/runs/{args.run_id}/signal"

    # Try the dedicated /cancel endpoint first.
    rc, payload = _post_json(cancel_url, body={}, headers=headers, timeout=args.timeout)
    if rc == 404:
        # Fallback: emit a cancel signal via the existing /signal route.
        rc, payload = _post_json(
            signal_url,
            body={"signal": "cancel"},
            headers=headers,
            timeout=args.timeout,
        )
    if rc == 200:
        print(payload)
        return 0
    print(f"HTTP {rc}: {payload}", file=sys.stderr)
    return 1


def _post_json(
    url: str,
    *,
    body: dict,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    opener = _build_opener(url)
    try:
        with opener.open(request, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return 0, f"connection_failed: {exc.reason}"


def _build_opener(url: str) -> urllib.request.OpenerDirector:
    """Build an opener that bypasses HTTP(S)_PROXY for localhost servers."""
    if "127.0.0.1" in url or "localhost" in url:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()
