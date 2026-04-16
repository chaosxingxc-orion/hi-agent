#!/usr/bin/env python
"""Quick smoke test — verifies a real LLM call works end-to-end.

Usage::

    # Fill in your API key in config/llm_config.json first, then:
    python scripts/verify_llm.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hi_agent.config.json_config_loader import load_from_json_config
from hi_agent.llm.protocol import LLMRequest


def main() -> None:
    cfg, builder = load_from_json_config()
    gateway = builder.build_llm_gateway()
    if gateway is None:
        print("ERROR: gateway is None — fill in api_key in config/llm_config.json")
        sys.exit(1)

    print(f"Gateway: {type(gateway).__name__}")
    req = LLMRequest(
        messages=[{"role": "user", "content": "Reply with exactly: hello"}],
        model="default",
        max_tokens=10,
        temperature=0.0,
    )
    resp = gateway.complete(req)
    print(f"Response : {resp.content!r}")
    print(f"Model    : {resp.model}")
    print(f"Usage    : {resp.usage}")
    print("✓ Real LLM call succeeded")


if __name__ == "__main__":
    main()
