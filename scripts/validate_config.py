#!/usr/bin/env python3
"""Validate hi-agent config JSON files against their schemas.

Usage:
    python scripts/validate_config.py config/tools.json
    python scripts/validate_config.py config/mcp_servers.json
    python scripts/validate_config.py config/   # validates all known configs in directory
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_SCHEMAS_DIR = _REPO_ROOT / "hi_agent" / "config" / "schemas"

_CONFIG_SCHEMA_MAP = {
    "tools.json": "tools.schema.json",
    "mcp_servers.json": "mcp_servers.schema.json",
    "llm_config.json": "llm_config.schema.json",
    "llm_config.example.json": "llm_config.schema.json",
}


def validate_file(config_path: Path) -> list[str]:
    """Validate a single config file. Returns list of error strings (empty = OK)."""
    schema_name = _CONFIG_SCHEMA_MAP.get(config_path.name)
    if schema_name is None:
        return []  # unknown file — skip silently
    schema_path = _SCHEMAS_DIR / schema_name
    if not schema_path.exists():
        return [f"Schema file not found: {schema_path}"]
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{config_path}: invalid JSON: {exc}"]
    try:
        import jsonschema

        jsonschema.validate(config, schema)
        return []
    except ImportError:
        # jsonschema not installed — fall back to basic type check
        if not isinstance(config, dict):
            return [f"{config_path}: expected a JSON object at root"]
        return []
    except Exception as exc:
        return [f"{config_path}: schema violation: {exc}"]


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_config.py <path>", file=sys.stderr)
        return 1
    target = Path(sys.argv[1])
    files: list[Path] = []
    if target.is_dir():
        files = [target / name for name in _CONFIG_SCHEMA_MAP if (target / name).exists()]
    elif target.is_file():
        files = [target]
    else:
        print(f"Error: {target} does not exist", file=sys.stderr)
        return 1
    all_errors: list[str] = []
    for f in files:
        errors = validate_file(f)
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        all_errors.extend(errors)
    if not all_errors:
        checked = [f.name for f in files] or ["(nothing to check)"]
        print(f"OK: {', '.join(checked)}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
