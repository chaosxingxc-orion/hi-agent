"""hi-agent extensions subcommand.

Subcommands:
    inspect  -- inspect a registered extension (with optional --explain and --posture flags)
    validate -- validate a manifest JSON/YAML file against ExtensionRegistry rules

Usage::

    hi-agent extensions inspect <name> <version> [--posture dev|research|prod] [--explain]
    hi-agent extensions validate <manifest-file>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.config.posture import Posture


def _load_posture(posture_name: str | None) -> Posture:
    """Return a Posture instance from the given name or the environment."""
    from hi_agent.config.posture import Posture

    if posture_name is not None:
        try:
            return Posture(posture_name.strip().lower())
        except ValueError:
            print(
                f"error: invalid --posture={posture_name!r}; must be dev, research, or prod",
                file=sys.stderr,
            )
            sys.exit(1)
    return Posture.from_env()


def run_inspect(args) -> None:
    """Inspect an extension manifest, optionally explaining production eligibility.

    Args:
        args: Parsed CLI arguments with name, version, posture, explain fields.
    """
    name: str = args.name
    version: str = args.version
    posture = _load_posture(getattr(args, "posture", None))
    explain: bool = getattr(args, "explain", False)

    # Attempt to load the plugin manifest from file system as a demo lookup.
    # In a full DI wiring, this would query a server-managed ExtensionRegistry.
    try:
        from hi_agent.plugin.manifest import PluginManifest

        # Search common plugin directories for a matching manifest.
        home_dir = Path.home() / ".hi_agent" / "plugins"
        search_dirs = [Path(".hi_agent/plugins"), home_dir]
        manifest = None
        for plugin_dir in search_dirs:
            candidate = plugin_dir / name / "plugin.json"
            if candidate.exists():
                try:
                    loaded = PluginManifest.from_json(candidate)
                    if loaded.version == version:
                        manifest = loaded
                        break
                except Exception:
                    pass

        if manifest is None:
            print(f"Extension {name}:{version} not found in plugin search paths.")
            sys.exit(1)

        print(f"Extension: {manifest.name}:{manifest.version}")
        print(f"  manifest_kind:          {manifest.manifest_kind}")
        print(f"  schema_version:         {manifest.schema_version}")
        print(f"  required_posture:       {manifest.required_posture}")
        print(f"  tenant_scope:           {manifest.tenant_scope}")
        print(f"  dangerous_capabilities: {manifest.dangerous_capabilities}")
        print(f"  config_schema:          {'present' if manifest.config_schema else 'None'}")
        print(f"  posture_support:        {manifest.posture_support}")

        if explain:
            eligible, reasons = manifest.production_eligibility(posture)
            print(f"\nProduction eligibility (posture={posture.value!r}):")
            if eligible:
                print("  ELIGIBLE — no blocking reasons.")
            else:
                print(f"  BLOCKED ({len(reasons)} reason(s)):")
                for i, reason in enumerate(reasons, 1):
                    print(f"    [{i}] {reason}")

    except SystemExit:
        raise
    except Exception as exc:
        print(f"error: inspect failed — {exc}", file=sys.stderr)
        sys.exit(1)


def run_validate(args) -> None:
    """Validate a manifest JSON file against ExtensionRegistry rules.

    Prints "PASS" and exits 0 on success.
    Prints "FAIL: <reasons>" and exits non-zero on failure.

    Args:
        args: Parsed CLI arguments with manifest_file and posture fields.
    """
    manifest_file = Path(args.manifest_file)
    posture = _load_posture(getattr(args, "posture", None))

    if not manifest_file.exists():
        print(f"FAIL: manifest file not found: {manifest_file}", file=sys.stderr)
        sys.exit(1)

    try:
        raw = manifest_file.read_text(encoding="utf-8")
        data: dict = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"FAIL: manifest file is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"FAIL: cannot read manifest file: {exc}", file=sys.stderr)
        sys.exit(1)

    # Build a minimal PluginManifest from the JSON data for dry-run validation.
    try:
        from hi_agent.contracts.extension_manifest import ExtensionRegistry
        from hi_agent.plugin.manifest import PluginManifest

        manifest = PluginManifest(
            name=data.get("name", ""),
            version=data.get("version", ""),
            description=data.get("description", ""),
            plugin_type=data.get("type", "capability"),
            capabilities=data.get("capabilities", []),
            skill_dirs=data.get("skill_dirs", []),
            mcp_servers=data.get("mcp_servers", []),
            entry_point=data.get("entry_point"),
            manifest_kind=data.get("manifest_kind", "plugin"),
            schema_version=data.get("schema_version", 1),
            posture_support=data.get(
                "posture_support", {"dev": True, "research": True, "prod": True}
            ),
            required_posture=data.get("required_posture", "any"),
            tenant_scope=data.get("tenant_scope", "tenant"),
            dangerous_capabilities=data.get("dangerous_capabilities", []),
            config_schema=data.get("config_schema"),
        )

        registry = ExtensionRegistry()
        registry.register(manifest, posture)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"FAIL: unexpected error during validation — {exc}", file=sys.stderr)
        sys.exit(1)

    print("PASS")
    sys.exit(0)


def build_extensions_parser(subparsers) -> None:
    """Attach the 'extensions' subcommand and its sub-subcommands to subparsers."""
    ext_parser = subparsers.add_parser(
        "extensions", help="Manage and validate extension manifests"
    )
    ext_sub = ext_parser.add_subparsers(dest="extensions_action")

    # inspect
    inspect_parser = ext_sub.add_parser("inspect", help="Inspect an extension manifest")
    inspect_parser.add_argument("name", help="Extension name")
    inspect_parser.add_argument("version", help="Extension version")
    inspect_parser.add_argument(
        "--posture",
        required=False,
        default=None,
        help="Posture to use for eligibility check (dev|research|prod). "
        "Defaults to HI_AGENT_POSTURE env var.",
    )
    inspect_parser.add_argument(
        "--explain",
        action="store_true",
        default=False,
        help="Print production eligibility breakdown field by field.",
    )

    # validate
    validate_parser = ext_sub.add_parser(
        "validate", help="Validate a manifest JSON file (dry-run registration)"
    )
    validate_parser.add_argument("manifest_file", help="Path to manifest JSON file")
    validate_parser.add_argument(
        "--posture",
        required=False,
        default=None,
        help="Posture to validate against (dev|research|prod). "
        "Defaults to HI_AGENT_POSTURE env var.",
    )


def run_extensions(args) -> None:
    """Dispatch extensions subcommands."""
    action = getattr(args, "extensions_action", None)
    if action == "inspect":
        run_inspect(args)
    elif action == "validate":
        run_validate(args)
    else:
        print("Usage: hi-agent extensions [inspect|validate]", file=sys.stderr)
        sys.exit(1)
