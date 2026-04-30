"""``agent-server`` CLI — argparse dispatcher (W24 I-E).

Entry point registered via ``[project.scripts]``::

    agent-server = "agent_server.cli.main:main"

Subcommands:
  * ``serve``       — boot the ASGI app
  * ``run``         — POST /v1/runs
  * ``cancel``      — POST /v1/runs/{id}/cancel
  * ``tail-events`` — GET /v1/runs/{id}/events (SSE stream)

This module is the operator-facing facade; per R-AS-1 it must NOT
import from ``hi_agent.*``. Per-command logic uses stdlib HTTP only.
"""
from __future__ import annotations

import argparse
import sys

from agent_server.cli.commands import cancel as cancel_cmd
from agent_server.cli.commands import run as run_cmd
from agent_server.cli.commands import serve as serve_cmd
from agent_server.cli.commands import tail_events as tail_events_cmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-server",
        description="agent-server northbound CLI (W24 I-E).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_cmd.register(subparsers)
    run_cmd.register(subparsers)
    cancel_cmd.register(subparsers)
    tail_events_cmd.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return 2
    return int(handler(args))


if __name__ == "__main__":
    sys.exit(main())
