"""``agent-server tail-events`` — stream SSE events for a run (W24 I-E).

The northbound run-events endpoint returns Server-Sent Events. This
command reads the stream line-by-line, parses the SSE framing, and
pretty-prints each event JSON. Stdlib only.

When the dedicated /v1/runs/{id}/events route is not yet present (it
ships with Track I-routes), the command falls back to polling
GET /v1/runs/{id} every 1 s and printing the status snapshot, so
operators always have something usable.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]  # expiry_wave: Wave 30
    parser = subparsers.add_parser(
        "tail-events",
        help="Stream events for a run from /v1/runs/{id}/events (SSE).",
    )
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout", type=float, default=300.0,
                        help="Maximum wall-clock seconds to stay attached.")
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="Polling cadence for the status fallback.")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    headers = {
        "Accept": "text/event-stream",
        "X-Tenant-Id": args.tenant,
    }
    base = args.server.rstrip("/")
    sse_url = f"{base}/v1/runs/{args.run_id}/events"

    request = urllib.request.Request(sse_url, method="GET", headers=headers)
    opener = _build_opener(args.server)
    try:
        return _consume_sse(request, opener=opener, timeout=args.timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # Fallback to status polling
            return _poll_status(
                base, args.tenant, args.run_id, args.timeout, args.poll_interval,
                opener=opener,
            )
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


def _consume_sse(
    request: urllib.request.Request,
    *,
    opener: urllib.request.OpenerDirector,
    timeout: float,
) -> int:
    deadline = time.monotonic() + timeout
    with opener.open(request, timeout=timeout) as resp:
        # Parse the SSE event stream as a sequence of "data: <json>" lines
        # separated by blank lines. Pretty-print each event JSON.
        buffer: list[str] = []
        while time.monotonic() < deadline:
            line = resp.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if decoded == "":
                if buffer:
                    _emit_event(buffer)
                    buffer.clear()
                continue
            if decoded.startswith(":"):
                continue  # SSE comment
            buffer.append(decoded)
        if buffer:
            _emit_event(buffer)
    return 0


def _emit_event(lines: list[str]) -> None:
    data_payloads = [ln[5:].lstrip() for ln in lines if ln.startswith("data:")]
    raw = "\n".join(data_payloads).strip()
    if not raw:
        return
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        print(raw)
        return
    print(json.dumps(parsed, ensure_ascii=False))


def _poll_status(
    base: str,
    tenant: str,
    run_id: str,
    timeout: float,
    poll_interval: float,
    *,
    opener: urllib.request.OpenerDirector,
) -> int:
    deadline = time.monotonic() + timeout
    headers = {"X-Tenant-Id": tenant}
    last_seen: str | None = None
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            f"{base}/v1/runs/{run_id}", method="GET", headers=headers
        )
        try:
            with opener.open(request, timeout=10.0) as resp:
                payload = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            print(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}",
                  file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"connection_failed: {exc.reason}", file=sys.stderr)
            return 1
        if payload != last_seen:
            print(payload)
            last_seen = payload
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {}
        if data.get("state") in {"succeeded", "failed", "cancelled", "timed_out"}:
            return 0
        time.sleep(poll_interval)
    print("tail-events: timed out before run reached terminal state",
          file=sys.stderr)
    return 0
