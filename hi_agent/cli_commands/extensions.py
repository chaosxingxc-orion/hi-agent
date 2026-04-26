"""hi-agent extensions subcommands — list and inspect registered extensions.

Usage::

    hi-agent extensions list [--format text|json] [--posture dev|research|prod]
    hi-agent extensions inspect <name>
"""

from __future__ import annotations

import json
import sys


def _cmd_extensions_list(args) -> None:
    """List all registered extensions, optionally filtered by posture."""
    from hi_agent.contracts.extension_manifest import get_extension_registry

    registry = get_extension_registry()
    posture = getattr(args, "posture", None)
    items = registry.list_for_posture(posture) if posture else registry.list_all()

    fmt = getattr(args, "fmt", "text")
    if fmt == "json":
        print(json.dumps([m.to_manifest_dict() for m in items], indent=2))
    else:
        if not items:
            print("No extensions registered.")
        for m in items:
            print(f"{m.name} ({m.manifest_kind}) v{m.version}")


def _cmd_extensions_inspect(args) -> None:
    """Show details for a single extension by name."""
    from hi_agent.contracts.extension_manifest import get_extension_registry

    registry = get_extension_registry()
    m = registry.lookup(args.name)
    if m is None:
        print(f"Extension '{args.name}' not found.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(m.to_manifest_dict(), indent=2))


def register_subparser(subparsers) -> None:
    """Add the 'extensions' subcommand group to *subparsers*."""
    ext_parser = subparsers.add_parser("extensions", help="Manage registered extensions")
    ext_sub = ext_parser.add_subparsers(dest="extensions_action")

    # extensions list
    list_parser = ext_sub.add_parser("list", help="List registered extensions")
    list_parser.add_argument(
        "--format",
        dest="fmt",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    list_parser.add_argument(
        "--posture",
        default=None,
        choices=["dev", "research", "prod"],
        help="Filter extensions by posture support",
    )

    # extensions inspect
    inspect_parser = ext_sub.add_parser("inspect", help="Show details for a single extension")
    inspect_parser.add_argument("name", help="Extension name to inspect")


def handle_extensions(args) -> None:
    """Dispatch extensions subcommand to the appropriate handler."""
    action = getattr(args, "extensions_action", None)
    if action == "list":
        _cmd_extensions_list(args)
    elif action == "inspect":
        _cmd_extensions_inspect(args)
    else:
        print("Usage: hi-agent extensions [list|inspect]", file=sys.stderr)
        sys.exit(1)
