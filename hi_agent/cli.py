"""Command-line interface for hi-agent.

Usage::

    python -m hi_agent serve [--host HOST] [--port PORT]
    python -m hi_agent run --goal "..." [--task-family FAMILY] [--risk-level LEVEL]
    python -m hi_agent status [--run-id RUN_ID]
    python -m hi_agent health
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _api_request(
    method: str,
    url: str,
    body: dict | None = None,
) -> tuple[int, dict]:
    """Make a JSON HTTP request using stdlib.

    Args:
        method: HTTP method.
        url: Full URL.
        body: Optional JSON-serializable body.

    Returns:
        Tuple of (status_code, parsed_json_body).
    """
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())
    except urllib.error.URLError as exc:
        return 0, {"error": f"connection_failed: {exc.reason}"}


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the API server."""
    from hi_agent.server.app import AgentServer

    server = AgentServer(host=args.host, port=args.port)
    server.start()


def _cmd_run(args: argparse.Namespace) -> None:
    """Submit a task run via the API server."""
    base = f"http://{args.api_host}:{args.api_port}"
    body = {
        "goal": args.goal,
        "task_family": args.task_family,
        "risk_level": args.risk_level,
    }
    status, data = _api_request("POST", f"{base}/runs", body)
    if args.json:
        print(json.dumps(data, indent=2))  # noqa: T201
    else:
        if status == 201:
            print(f"Run created: {data.get('run_id')} (state={data.get('state')})")  # noqa: T201
        else:
            print(f"Error ({status}): {data}", file=sys.stderr)  # noqa: T201
            sys.exit(1)


def _cmd_status(args: argparse.Namespace) -> None:
    """Query run status."""
    base = f"http://{args.api_host}:{args.api_port}"
    if args.run_id:
        status, data = _api_request("GET", f"{base}/runs/{args.run_id}")
    else:
        status, data = _api_request("GET", f"{base}/runs")
    print(json.dumps(data, indent=2))  # noqa: T201
    if status >= 400:
        sys.exit(1)


def _cmd_health(args: argparse.Namespace) -> None:
    """Check server health."""
    base = f"http://{args.api_host}:{args.api_port}"
    status, data = _api_request("GET", f"{base}/health")
    print(json.dumps(data, indent=2))  # noqa: T201
    if status != 200:
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(description="hi-agent TRACE framework")
    parser.add_argument(
        "--api-host",
        default="127.0.0.1",
        help="API server host for client commands (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=8080,
        help="API server port for client commands (default: 8080)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start API server")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8080)

    # run
    run_parser = subparsers.add_parser("run", help="Execute a task")
    run_parser.add_argument("--goal", required=True)
    run_parser.add_argument("--task-family", default="quick_task")
    run_parser.add_argument("--risk-level", default="low")
    run_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # status
    status_parser = subparsers.add_parser("status", help="Check run status")
    status_parser.add_argument("--run-id", required=False)

    # health
    subparsers.add_parser("health", help="Check system health")

    return parser


def main() -> None:
    """Entry point for the hi-agent CLI."""
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "serve": _cmd_serve,
        "run": _cmd_run,
        "status": _cmd_status,
        "health": _cmd_health,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
