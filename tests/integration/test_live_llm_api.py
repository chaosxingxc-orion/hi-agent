"""Real API integration tests — live model calls through HttpLLMGateway.

Every test in this module makes actual HTTP calls to the Volces Ark API.
They are **excluded from the default test run** and must be invoked explicitly.

How to run (no env var needed — config auto-loaded from config/llm_config.json)::

    python -m pytest tests/integration/test_live_llm_api.py -v -m live_api

All parameters (base_url, api_key, models, timeout) are read from
``config/llm_config.json`` (``providers.volces`` section) via ``tests/conftest.py``.
Override with env vars (``VOLCE_API_KEY``, ``VOLCE_BASE_URL``) for CI.

Architecture context (traced before writing, per Rule 0):
- ``HttpLLMGateway._post()`` calls ``{base_url}/chat/completions``.
- The API key is read from the env var named by ``api_key_env`` constructor arg.
- All models share one base URL — unified proxy at Volces Ark.
- LLMRequest.messages: ``[{role, content}]`` — standard OpenAI format.
- LLMResponse.content: plain string extracted from ``choices[0].message.content``.
- Tests skip automatically when ``VOLCE_API_KEY`` is not set.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path

import pytest

from hi_agent.llm.http_gateway import HttpLLMGateway
from hi_agent.llm.protocol import LLMRequest


# ---------------------------------------------------------------------------
# Load config from config/llm_config.json (providers.volces)
# ---------------------------------------------------------------------------

_LLM_CONFIG = Path(__file__).parent.parent.parent / "config" / "llm_config.json"
_vcfg: dict = {}
if _LLM_CONFIG.exists():
    _vcfg = json.loads(_LLM_CONFIG.read_text()).get("providers", {}).get("volces", {})

_API_KEY_ENV = "VOLCE_API_KEY"
_BASE_URL = os.environ.get("VOLCE_BASE_URL", _vcfg.get("base_url", ""))
_TIMEOUT = _vcfg.get("timeout_seconds", 60)
_MAX_RETRIES = _vcfg.get("max_retries", 1)
_ALL_MODELS: list[str] = _vcfg.get("all_models", [])


def _unique_non_empty(values: object) -> list[str]:
    """Return unique, non-empty string values while preserving order."""
    if not isinstance(values, Iterable) or isinstance(values, str | bytes):
        return []
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in result:
            result.append(value)
    return result


def _behavior_models() -> list[str]:
    """Select models for multi-call behavioral checks.

    CI should validate every catalog model with cheap smoke/latency calls, but
    multi-turn and code-generation checks are intentionally scoped to the
    production routing models. Set VOLCE_LIVE_BEHAVIOR_MODELS=all to run the
    full catalog behavior matrix manually.
    """
    override = os.environ.get("VOLCE_LIVE_BEHAVIOR_MODELS", "").strip()
    if override.lower() == "all":
        return _ALL_MODELS
    if override:
        return _unique_non_empty([item.strip() for item in override.split(",")])

    configured = _vcfg.get("models", {})
    if isinstance(configured, dict):
        selected = _unique_non_empty([
            configured.get("strong"),
            configured.get("medium"),
            configured.get("light"),
        ])
        if selected:
            return selected
    return _ALL_MODELS[:1]


_BEHAVIOR_MODELS = _behavior_models()

# Skip the entire module when the API key is absent.
# Default key is loaded from config/llm_config.json via conftest.py; override with env var for CI.
pytestmark = pytest.mark.skipif(
    not os.environ.get(_API_KEY_ENV),
    reason=f"{_API_KEY_ENV} not set — skip live API tests. "
           f"Run: pytest tests/integration/test_live_llm_api.py -m live_api -v",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _inject_api_key() -> None:
    """Ensure VOLCE_API_KEY is available to HttpLLMGateway for the whole module."""
    # Already guaranteed by pytestmark skipif; this fixture is a safety net
    # for sub-fixtures that construct the gateway before the skipif fires.
    key = os.environ.get(_API_KEY_ENV, "")
    if key:
        os.environ[_API_KEY_ENV] = key


@pytest.fixture()
def gateway() -> HttpLLMGateway:
    """Return a configured HttpLLMGateway for the Volces Ark endpoint."""
    return HttpLLMGateway(
        base_url=_BASE_URL,
        api_key_env=_API_KEY_ENV,
        timeout_seconds=_TIMEOUT,
        max_retries=_MAX_RETRIES,
        retry_base_seconds=1.0,
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _minimal_request(model: str, content: str = "Reply with the single word: ready") -> LLMRequest:
    """Build a short, cheap LLMRequest for smoke testing."""
    return LLMRequest(
        messages=[{"role": "user", "content": content}],
        model=model,
        temperature=0.0,
        max_tokens=64,
    )


def _assert_valid_response(resp: object, model: str) -> None:
    """Assert that the response satisfies the LLMResponse contract."""
    from hi_agent.llm.protocol import LLMResponse  # noqa: PLC0415

    assert isinstance(resp, LLMResponse), f"Expected LLMResponse, got {type(resp)}"
    assert resp.content, f"[{model}] response.content is empty"
    assert resp.finish_reason in ("stop", "length", "content_filter", "tool_calls"), (
        f"[{model}] unexpected finish_reason: {resp.finish_reason!r}"
    )
    assert resp.usage.prompt_tokens > 0, f"[{model}] prompt_tokens must be > 0"
    assert resp.usage.completion_tokens > 0, f"[{model}] completion_tokens must be > 0"
    assert resp.model, f"[{model}] response.model is empty"


# ---------------------------------------------------------------------------
# TC-1: Smoke completion — one call per model
# ---------------------------------------------------------------------------

@pytest.mark.live_api
@pytest.mark.parametrize("model", _ALL_MODELS)
def test_smoke_completion(gateway: HttpLLMGateway, model: str) -> None:
    """Each model must respond to a minimal prompt with valid structure.

    Verifies:
    - HTTP call succeeds (no LLMProviderError / LLMTimeoutError)
    - response.content is non-empty
    - response.finish_reason is a known value
    - input_tokens and output_tokens are positive
    - response.model is populated
    """
    request = _minimal_request(model)
    resp = gateway.complete(request)
    _assert_valid_response(resp, model)


# ---------------------------------------------------------------------------
# TC-2: Multi-turn conversation — context is preserved across turns
# ---------------------------------------------------------------------------

@pytest.mark.live_api
@pytest.mark.parametrize("model", _BEHAVIOR_MODELS)
def test_multi_turn_conversation(gateway: HttpLLMGateway, model: str) -> None:
    """Model must maintain context across a two-turn exchange.

    Turn 1: introduce a secret number.
    Turn 2: ask the model to recall it.
    Pass criterion: the number appears in the second response.
    """
    secret = "42"
    messages: list[dict] = [
        {"role": "user", "content": f"Remember the secret number {secret}. Acknowledge with 'ok'."},
    ]

    # Turn 1
    resp1 = gateway.complete(LLMRequest(messages=messages, model=model, temperature=0.0, max_tokens=32))
    _assert_valid_response(resp1, model)

    # Append assistant reply and ask follow-up
    messages.append({"role": "assistant", "content": resp1.content})
    messages.append({"role": "user", "content": "What was the secret number? Reply with the number only."})

    # Turn 2
    resp2 = gateway.complete(LLMRequest(messages=messages, model=model, temperature=0.0, max_tokens=16))
    _assert_valid_response(resp2, model)

    assert secret in resp2.content, (
        f"[{model}] Expected secret '{secret}' in second turn response, got: {resp2.content!r}"
    )


# ---------------------------------------------------------------------------
# TC-3: Code generation — code-oriented models produce syntactically useful output
# ---------------------------------------------------------------------------

@pytest.mark.live_api
@pytest.mark.parametrize("model", _BEHAVIOR_MODELS)
def test_code_generation(gateway: HttpLLMGateway, model: str) -> None:
    """Model must return a Python function when asked.

    Pass criterion: response contains 'def' (function keyword).
    This is intentionally lenient — formatting varies across models.
    """
    request = LLMRequest(
        messages=[{
            "role": "user",
            "content": "Write a Python function that returns the sum of a list of numbers. "
                       "Output only the function definition, no explanation.",
        }],
        model=model,
        temperature=0.0,
        max_tokens=256,
    )
    resp = gateway.complete(request)
    _assert_valid_response(resp, model)

    assert "def " in resp.content, (
        f"[{model}] Code generation response should contain 'def', got: {resp.content[:200]!r}"
    )


# ---------------------------------------------------------------------------
# TC-4: Sequential calls — gateway state does not leak between requests
# ---------------------------------------------------------------------------

@pytest.mark.live_api
def test_sequential_calls_no_state_leak(gateway: HttpLLMGateway) -> None:
    """Two sequential calls with different models must not share state.

    Uses doubao-seed-2.0-lite (fastest) for both calls.
    Verifies that the second response is independent of the first.
    """
    model = "doubao-seed-2.0-lite"

    r1 = gateway.complete(LLMRequest(
        messages=[{"role": "user", "content": "The colour is red. Acknowledge with 'ok'."}],
        model=model,
        temperature=0.0,
        max_tokens=16,
    ))

    r2 = gateway.complete(LLMRequest(
        messages=[{"role": "user", "content": "What colour did I mention? Reply with 'none'."}],
        model=model,
        temperature=0.0,
        max_tokens=16,
    ))

    _assert_valid_response(r1, model)
    _assert_valid_response(r2, model)

    # Second request has no history — model should NOT mention red.
    # It is sent only "What colour did I mention?" with no prior context,
    # so "red" must not appear in the response.
    assert "red" not in r2.content.lower(), (
        f"[{model}] State leaked between calls — second response mentions 'red': {r2.content!r}"
    )


# ---------------------------------------------------------------------------
# TC-5: Latency guard — each model responds within 30 seconds
# ---------------------------------------------------------------------------

@pytest.mark.live_api
@pytest.mark.parametrize("model", _ALL_MODELS)
def test_response_latency(gateway: HttpLLMGateway, model: str) -> None:
    """Each model must respond to a minimal prompt within 30 s.

    This catches hung connections, rate-limit spin-loops, or misconfigured
    endpoints before they silently degrade production throughput.
    """
    deadline = 30.0
    start = time.monotonic()

    request = _minimal_request(model, "Respond with the single word: ok")
    resp = gateway.complete(request)

    elapsed = time.monotonic() - start
    _assert_valid_response(resp, model)

    assert elapsed < deadline, (
        f"[{model}] Response took {elapsed:.1f}s — exceeds {deadline}s deadline"
    )
