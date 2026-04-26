#!/usr/bin/env python3
"""Inject a Volces API key into config/llm_config.json for CI/test runs.

Reads the key from VOLCES_KEY env var (default) or --from-secret <ENV_VAR>.
Registers an atexit hook to restore the original file content on exit.

Usage:
    VOLCES_KEY=<key> python scripts/inject_volces_key.py
    python scripts/inject_volces_key.py --from-secret VOLCES_KEY

Guards:
- Refuses to run if config/llm_config.json has uncommitted local changes
  (unless INJECT_FORCE=1 is set).
- Restores original file content on process exit via atexit.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "llm_config.json"


def _dirty_check() -> None:
    """Abort if config/llm_config.json has uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain", str(CONFIG_PATH)],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() and not os.environ.get("INJECT_FORCE", ""):
        print("ERROR: config/llm_config.json has uncommitted changes.", file=sys.stderr)
        print("Commit or stash the changes first, or set INJECT_FORCE=1 to override.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject Volces API key into llm_config.json")
    parser.add_argument("--from-secret", default="", help="Env var name holding the key (default: VOLCES_KEY)")
    args = parser.parse_args()

    secret_var = args.from_secret or "VOLCES_KEY"
    key = os.environ.get(secret_var, "")
    if not key:
        print(f"SKIP: env var {secret_var} is empty", flush=True)
        sys.exit(0)

    _dirty_check()

    original_content = CONFIG_PATH.read_text(encoding="utf-8")

    def _restore_original() -> None:
        try:
            CONFIG_PATH.write_text(original_content, encoding="utf-8")
            print("inject_volces_key.py: restored original config/llm_config.json")
        except OSError as e:
            print(f"inject_volces_key.py: WARNING — failed to restore config: {e}", file=sys.stderr)

    atexit.register(_restore_original)

    data = json.loads(original_content)
    data.setdefault("providers", {}).setdefault("volces", {})["api_key"] = key
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"inject_volces_key.py: injected key into {CONFIG_PATH} (will restore on exit)", flush=True)


if __name__ == "__main__":
    main()
