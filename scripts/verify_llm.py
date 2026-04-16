#!/usr/bin/env python
"""Quick smoke test — verifies a real LLM call works end-to-end.

Reads config/llm_config.json, activates the ``default_provider``, and sends
one minimal request.  Supports any provider (Anthropic, OpenAI, DashScope
coding plan, etc.) as long as it has an ``api_key`` and ``base_url`` filled in.

Usage::

    # 1. Fill in api_key for your chosen provider in config/llm_config.json
    # 2. Set "default_provider" to that provider name
    # 3. Run:
    python scripts/verify_llm.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hi_agent.config.json_config_loader import build_gateway_from_config
from hi_agent.llm.protocol import LLMRequest


def main() -> None:
    gateway = build_gateway_from_config()
    if gateway is None:
        print(
            "ERROR: gateway is None\n"
            "  → Fill in 'api_key' for the active 'default_provider' "
            "in config/llm_config.json"
        )
        sys.exit(1)

    print(f"Gateway : {type(gateway).__name__}")
    inner = getattr(gateway, "_inner", gateway)
    print(f"Backend : {type(inner).__name__}  model={getattr(inner, '_default_model', '?')}")

    req = LLMRequest(
        messages=[{"role": "user", "content": "Reply with exactly: hello"}],
        model="default",
        max_tokens=20,
        temperature=0.0,
    )
    resp = gateway.complete(req)
    print(f"Response: {resp.content!r}")
    print(f"Model   : {resp.model}")
    print(f"Usage   : in={resp.usage.prompt_tokens} out={resp.usage.completion_tokens}")
    print("OK: Real LLM call succeeded")


if __name__ == "__main__":
    main()
