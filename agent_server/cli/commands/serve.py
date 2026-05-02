"""``agent-server serve`` — boot the northbound HTTP facade (W24 I-E).

Per R-AS-1 the CLI may NOT import ``hi_agent.*``. We therefore delegate
to ``python -m hi_agent serve`` which the runtime team owns. The
agent-server CLI is the operator-facing entry point; the heavy lifting
lives behind the existing module entrypoint.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]  # expiry_wave: permanent
    parser = subparsers.add_parser(
        "serve",
        help="Boot the agent_server ASGI app (delegates to python -m hi_agent serve).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Set HI_AGENT_ENV=prod (real credentials required).",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cmd = [sys.executable, "-m", "hi_agent", "serve",
           "--host", str(args.host),
           "--port", str(args.port)]
    if getattr(args, "prod", False):
        cmd.append("--prod")
    env = dict(os.environ)
    return subprocess.call(cmd, env=env)
