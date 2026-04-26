#!/usr/bin/env python3
"""CI utility: inject VOLCE_API_KEY secret into config/llm_config.json.
Called once during CI setup; never called by production runtime.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-secret", required=True, help="Env var name holding the key")
    args = parser.parse_args()
    key = os.environ.get(args.from_secret, "")
    if not key:
        print(f"SKIP: env var {args.from_secret} is empty", flush=True)
        sys.exit(0)
    cfg_path = ROOT / "config" / "llm_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("providers", {}).setdefault("volces", {})["api_key"] = key
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK: injected key into {cfg_path}", flush=True)


if __name__ == "__main__":
    main()
