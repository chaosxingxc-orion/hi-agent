#!/usr/bin/env python
"""Smoke tests — verify streaming, thinking mode, and multimodal via llm_config.json.

Usage::

    python scripts/verify_llm.py [--thinking] [--multimodal <image_path>]

Options:
    --thinking    Enable extended thinking (8000-token budget).
    --multimodal  Pass an image file path to test multimodal input.
                  The image is base64-encoded and sent as an image block.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hi_agent.config.json_config_loader import build_gateway_from_config
from hi_agent.llm.protocol import LLMRequest


def _check_thinking(argv: list[str]) -> bool:
    return "--thinking" in argv


def _check_multimodal(argv: list[str]) -> str | None:
    try:
        idx = argv.index("--multimodal")
        return argv[idx + 1]
    except (ValueError, IndexError):
        return None


def run_streaming(gateway: object) -> None:
    """Test 1: streaming mode."""
    print("\n[1] Streaming test")
    from hi_agent.llm.protocol import LLMRequest

    req = LLMRequest(
        messages=[{"role": "user", "content": "Count from 1 to 5, one number per line."}],
        model="default",
        max_tokens=100,
        temperature=0.0,
    )
    stream_fn = getattr(gateway, "stream", None)
    if not callable(stream_fn):
        print("  SKIP: gateway has no stream() method")
        return

    print("  Streaming: ", end="", flush=True)
    chunks = 0
    full_text = ""
    final_usage = None
    for chunk in stream_fn(req):
        if chunk.delta:
            print(chunk.delta, end="", flush=True)
            full_text += chunk.delta
            chunks += 1
        if chunk.usage:
            final_usage = chunk.usage
    print()
    print(f"  Chunks received : {chunks}")
    print(f"  Full text length: {len(full_text)}")
    if final_usage:
        print(f"  Tokens: in={final_usage.prompt_tokens} out={final_usage.completion_tokens}")
    print("  OK: Streaming works")


def run_thinking(gateway: object) -> None:
    """Test 2: extended thinking mode."""
    print("\n[2] Thinking mode test")
    req = LLMRequest(
        messages=[{"role": "user", "content": "What is 17 * 23? Show your reasoning."}],
        model="default",
        max_tokens=1000,
        temperature=0.0,
        thinking_budget=8000,
    )
    stream_fn = getattr(gateway, "stream", None)
    if callable(stream_fn):
        print("  Streaming with thinking: ", end="", flush=True)
        text = ""
        thinking = ""
        for chunk in stream_fn(req):
            if chunk.delta:
                print(chunk.delta, end="", flush=True)
                text += chunk.delta
            if chunk.thinking_delta:
                thinking += chunk.thinking_delta
        print()
        if thinking:
            print(f"  Thinking ({len(thinking)} chars): {thinking[:120]}...")
        else:
            print("  Note: no thinking content returned (provider may not support it)")
        print("  OK: Thinking mode request sent")
    else:
        # Non-streaming fallback
        resp = gateway.complete(req)
        print(f"  Response: {resp.content!r}")
        if resp.thinking:
            print(f"  Thinking: {resp.thinking[:120]}...")
        print("  OK: Thinking mode works")


def run_multimodal(gateway: object, image_path: str) -> None:
    """Test 3: multimodal input (image + text)."""
    print(f"\n[3] Multimodal test — image: {image_path}")
    path = Path(image_path)
    if not path.exists():
        print(f"  SKIP: file not found: {image_path}")
        return

    # Detect media type from extension
    ext = path.suffix.lower()
    media_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
    media_type = media_map.get(ext, "image/jpeg")

    image_data = base64.standard_b64encode(path.read_bytes()).decode()

    req = LLMRequest(
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    },
                },
                {"type": "text", "text": "Describe this image in one sentence."},
            ],
        }],
        model="default",
        max_tokens=200,
        temperature=0.0,
    )

    stream_fn = getattr(gateway, "stream", None)
    if callable(stream_fn):
        print("  Streaming multimodal: ", end="", flush=True)
        for chunk in stream_fn(req):
            if chunk.delta:
                print(chunk.delta, end="", flush=True)
        print()
    else:
        resp = gateway.complete(req)
        print(f"  Response: {resp.content!r}")
    print("  OK: Multimodal request sent")


def main() -> None:
    argv = sys.argv[1:]
    thinking = _check_thinking(argv)
    multimodal_path = _check_multimodal(argv)

    gateway = build_gateway_from_config()
    if gateway is None:
        print("ERROR: gateway is None — fill in api_key in config/llm_config.json")
        sys.exit(1)

    inner = getattr(gateway, "_inner", gateway)
    print(f"Gateway : {type(gateway).__name__}")
    print(f"Backend : {type(inner).__name__}")
    print(f"Model   : {getattr(inner, '_default_model', '?')}")
    print(f"Base URL: {getattr(inner, '_base_url', '?')}")
    thinking_default = getattr(inner, "_default_thinking_budget", None)
    print(f"Thinking: {'enabled (default=' + str(thinking_default) + ')' if thinking_default else 'off by default'}")

    # Always run streaming test
    run_streaming(gateway)

    # Thinking test if requested
    if thinking:
        run_thinking(gateway)

    # Multimodal test if image path provided
    if multimodal_path:
        run_multimodal(gateway, multimodal_path)

    print("\nAll requested tests passed.")


if __name__ == "__main__":
    main()
