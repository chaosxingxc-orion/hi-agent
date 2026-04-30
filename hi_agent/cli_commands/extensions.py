"""hi-agent extensions subcommand.

Subcommands:
    list     -- list registered extensions (with optional --format and --posture flags)
    inspect  -- inspect a registered extension (with optional --explain and --posture flags)
    validate -- validate a manifest JSON/YAML file against ExtensionRegistry rules

Usage::

    hi-agent extensions list [--format text|json] [--posture dev|research|prod]
    hi-agent extensions inspect <name> [<version>] [--posture dev|research|prod] [--explain]
    hi-agent extensions validate <manifest-file>
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from hi_agent.observability.metric_counter import Counter

logger = logging.getLogger(__name__)
_ext_errors_total = Counter("hi_agent_cli_extensions_errors_total")

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


def _manifest_to_dict(manifest) -> dict:
    """Serialize a manifest to a plain dict for JSON output."""
    return {
        "name": getattr(manifest, "name", ""),
        "version": getattr(manifest, "version", ""),
        "manifest_kind": getattr(manifest, "manifest_kind", ""),
        "schema_version": getattr(manifest, "schema_version", 1),
        "required_posture": getattr(manifest, "required_posture", "any"),
        "tenant_scope": getattr(manifest, "tenant_scope", "tenant"),
        "dangerous_capabilities": list(getattr(manifest, "dangerous_capabilities", [])),
        "posture_support": dict(getattr(manifest, "posture_support", {})),
        "config_schema": getattr(manifest, "config_schema", None),
    }


def run_list(args) -> None:
    """List registered extensions.

    Args:
        args: Parsed CLI arguments with format and posture fields.
    """
    from hi_agent.contracts.extension_manifest import get_extension_registry

    fmt: str = getattr(args, "format", "text") or "text"
    posture_name: str | None = getattr(args, "posture", None)
    registry = get_extension_registry()

    manifests = registry.list_for_posture(posture_name) if posture_name else registry.list_all()

    if fmt == "json":
        print(json.dumps([_manifest_to_dict(m) for m in manifests], indent=2))
    else:
        if not manifests:
            print("No extensions registered.")
        else:
            for m in manifests:
                print(f"{getattr(m, 'name', '?')} {getattr(m, 'version', '?')}")


def run_inspect(args) -> None:
    """Inspect an extension manifest, optionally explaining production eligibility.

    Args:
        args: Parsed CLI arguments with name, version, posture, explain fields.
    """
    from hi_agent.contracts.extension_manifest import get_extension_registry

    name: str = args.name
    version: str | None = getattr(args, "version", None)
    posture = _load_posture(getattr(args, "posture", None))
    explain: bool = getattr(args, "explain", False)

    registry = get_extension_registry()
    all_manifests = registry.list_all()
    manifest = None
    for m in all_manifests:
        if getattr(m, "name", None) == name and (
            version is None or getattr(m, "version", None) == version
        ):
            manifest = m
            break

    if manifest is None:
        label = f"{name}:{version}" if version else name
        print(f"error: extension {label!r} not found", file=sys.stderr)
        sys.exit(1)

    try:
        data = _manifest_to_dict(manifest)
        if explain:
            eligible, reasons = manifest.production_eligibility(posture)
            data["production_eligibility"] = {
                "posture": posture.value,
                "eligible": eligible,
                "reasons": reasons,
            }
        print(json.dumps(data, indent=2))
    except SystemExit:
        raise
    except Exception as exc:
        _ext_errors_total.inc()
        logger.warning("extensions.inspect_error error=%s", exc)
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
        from hi_agent.plugins.manifest import PluginManifest

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
        _ext_errors_total.inc()
        logger.warning("extensions.validate_error error=%s", exc)
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

    # list
    list_parser = ext_sub.add_parser("list", help="List registered extensions")
    list_parser.add_argument(
        "--format",
        dest="format",
        default="text",
        choices=["text", "json"],
        help="Output format (text or json). Default: text.",
    )
    list_parser.add_argument(
        "--posture",
        required=False,
        default=None,
        help="Filter by posture support (dev|research|prod).",
    )

    # inspect
    inspect_parser = ext_sub.add_parser("inspect", help="Inspect an extension manifest")
    inspect_parser.add_argument("name", help="Extension name")
    inspect_parser.add_argument(
        "version",
        nargs="?",
        default=None,
        help="Extension version (omit to match any version).",
    )
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
    if action == "list":
        run_list(args)
    elif action == "inspect":
        run_inspect(args)
    elif action == "validate":
        run_validate(args)
    else:
        print("Usage: hi-agent extensions [list|inspect|validate]", file=sys.stderr)
        sys.exit(1)


# Backwards-compatible alias for existing callers.
handle_extensions = run_extensions
