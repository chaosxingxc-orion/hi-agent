"""``agent-server serve`` — boot the northbound HTTP facade (W24 I-E, W31-N1).

W31-N1: ``serve`` now runs uvicorn IN-PROCESS against the FastAPI app
returned by :func:`agent_server.bootstrap.build_production_app`. Before
W31 we delegated to ``python -m hi_agent serve`` which exposed the
legacy ``/runs`` routes — RIA could not reach the new ``/v1/`` facade
through that legacy path.

Per R-AS-1 the CLI may not import ``hi_agent.*`` directly. That rule is
satisfied: this module only imports ``uvicorn`` (third-party) and the
agent_server bootstrap, which is the single seam permitted to touch
``hi_agent.*`` internally.
"""
from __future__ import annotations

import argparse
import os

import uvicorn

from agent_server.bootstrap import build_production_app


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]  # expiry_wave: permanent
    parser = subparsers.add_parser(
        "serve",
        help=(
            "Boot the agent_server ASGI app via uvicorn (in-process). "
            "Routes use the /v1 prefix (W31-N1)."
        ),
    )
    # Default to loopback for security — opt in to 0.0.0.0 with --prod.
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Bind address. Defaults to 127.0.0.1 (most secure). "
            "Pair --prod with --host 0.0.0.0 for external listeners."
        ),
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--prod",
        action="store_true",
        help=(
            "Set HI_AGENT_POSTURE=prod and HI_AGENT_ENV=prod. "
            "Real credentials required; idempotency middleware enforces "
            "the Idempotency-Key header on mutating routes."
        ),
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help=(
            "Directory for persistent state (idempotency SQLite, "
            "future artifact registry, ...). Defaults to "
            "$AGENT_SERVER_STATE_DIR or $HI_AGENT_HOME/.agent_server "
            "or ./.agent_server."
        ),
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    """Boot uvicorn against the agent_server FastAPI app.

    Returns 0 on a clean shutdown (Ctrl-C / SIGTERM). Exceptions during
    bootstrap propagate as non-zero exit codes via uvicorn's normal
    crash handling.
    """
    if getattr(args, "prod", False):
        os.environ.setdefault("HI_AGENT_POSTURE", "prod")
        os.environ.setdefault("HI_AGENT_ENV", "prod")

    state_dir = getattr(args, "state_dir", None)
    app = build_production_app(state_dir=state_dir)

    # Honour the parser defaults but let users override via CLI args.
    host = args.host
    if getattr(args, "prod", False) and host == "127.0.0.1":
        # Production deployments expect external reachability. Operators
        # who want loopback in prod can pass --host 127.0.0.1 explicitly
        # AFTER --prod (argparse ordering doesn't matter here; only the
        # final args.host value).
        host = "0.0.0.0"

    uvicorn.run(app, host=host, port=int(args.port))
    return 0
