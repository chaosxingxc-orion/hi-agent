#!/usr/bin/env python3
"""Inject a provider API key into config/llm_config.local.json for T3 gate runs.

Usage:
    python scripts/inject_provider_key.py [--provider {volces,anthropic,openai,auto}]

The key is read from the corresponding env var:
  volces:    VOLCES_API_KEY  (also accepts legacy VOLCES_KEY)
  anthropic: ANTHROPIC_API_KEY
  openai:    OPENAI_API_KEY
  auto:      first non-empty from the above list

The config is written to config/llm_config.local.json (gitignored).
The original config/llm_config.json is never modified.

Run with --restore to remove the local config.
Run with --strict to refuse if llm_config.local.json already exists.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "llm_config.json"
LOCAL_CONFIG_PATH = ROOT / "config" / "llm_config.local.json"

# Mapping: provider name -> env var names to check (in order)
_PROVIDER_ENV_VARS: dict[str, list[str]] = {
    "volces": ["VOLCES_API_KEY", "VOLCES_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
}

_AUTO_ORDER = ["volces", "anthropic", "openai"]


def _resolve_key(provider: str) -> tuple[str, str]:
    """Return (provider, key) for the given provider name.

    Raises SystemExit if no key is found.
    """
    env_vars = _PROVIDER_ENV_VARS.get(provider, [])
    for var in env_vars:
        key = os.environ.get(var, "")
        if key:
            return provider, key
    checked = ", ".join(env_vars) if env_vars else "(none)"
    print(
        f"ERROR: no key found for provider '{provider}'. "
        f"Checked env vars: {checked}",
        file=sys.stderr,
    )
    sys.exit(1)


def _resolve_auto() -> tuple[str, str]:
    """Try each provider in order and return the first with a key."""
    for provider in _AUTO_ORDER:
        for var in _PROVIDER_ENV_VARS[provider]:
            key = os.environ.get(var, "")
            if key:
                return provider, key
    all_vars = [v for vars_ in _PROVIDER_ENV_VARS.values() for v in vars_]
    checked = ", ".join(all_vars)
    print(
        f"ERROR: no provider key found (--provider auto). "
        f"Checked env vars: {checked}",
        file=sys.stderr,
    )
    sys.exit(1)


def _restore(*, quiet: bool = False) -> None:
    """Remove config/llm_config.local.json if it exists."""
    if LOCAL_CONFIG_PATH.exists():
        LOCAL_CONFIG_PATH.unlink()
        if not quiet:
            print(f"inject_provider_key: removed {LOCAL_CONFIG_PATH}")
    else:
        if not quiet:
            print(f"inject_provider_key: {LOCAL_CONFIG_PATH} does not exist, nothing to remove")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inject provider API key into config/llm_config.local.json"
    )
    parser.add_argument(
        "--provider",
        choices=["volces", "anthropic", "openai", "auto"],
        default="auto",
        help="Provider to inject key for (default: auto)",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Remove config/llm_config.local.json and exit",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Refuse to run if config/llm_config.local.json already exists",
    )
    args = parser.parse_args()

    if args.restore:
        _restore()
        return

    if args.strict and LOCAL_CONFIG_PATH.exists():
        print(
            f"ERROR: {LOCAL_CONFIG_PATH} already exists. "
            "Remove it first or omit --strict.",
            file=sys.stderr,
        )
        sys.exit(1)

    if LOCAL_CONFIG_PATH.exists():
        print(
            f"WARNING: {LOCAL_CONFIG_PATH} already exists and will be overwritten.",
            file=sys.stderr,
        )

    # Resolve provider and key
    if args.provider == "auto":
        provider, key = _resolve_auto()
    else:
        provider, key = _resolve_key(args.provider)

    # Load base config
    if not CONFIG_PATH.exists():
        print(f"ERROR: base config {CONFIG_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    # Inject: set default_provider and inject the key
    data["default_provider"] = provider
    data.setdefault("providers", {}).setdefault(provider, {})["api_key"] = key

    LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"inject_provider_key: injected {provider} key into {LOCAL_CONFIG_PATH}",
        flush=True,
    )


if __name__ == "__main__":
    main()
