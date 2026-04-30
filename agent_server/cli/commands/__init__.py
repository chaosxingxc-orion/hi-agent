"""agent-server CLI subcommands (W24 I-E).

Each module here exposes a ``register(subparsers)`` function and a
``run(args)`` handler. They use stdlib ``urllib.request`` only — no
imports from ``hi_agent.*`` are allowed inside ``agent_server/cli/``
per R-AS-1.
"""
