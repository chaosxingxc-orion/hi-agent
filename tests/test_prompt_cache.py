"""Tests for hi_agent.llm.cache — Prompt Caching support."""

from __future__ import annotations

import pytest
from hi_agent.llm.cache import (
    CacheAwareTokenUsage,
    PromptCacheConfig,
    PromptCacheInjector,
    PromptCacheStats,
    parse_cache_usage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_messages(n: int, content_as_list: bool = False) -> list[dict]:
    """Return *n* simple user messages."""
    msgs = []
    for i in range(n):
        content = [{"type": "text", "text": f"message {i}"}] if content_as_list else f"message {i}"
        msgs.append({"role": "user", "content": content})
    return msgs


# ---------------------------------------------------------------------------
# inject() — string content
# ---------------------------------------------------------------------------


def test_inject_string_content():
    """String content is converted to a list block with cache_control."""
    injector = PromptCacheInjector(PromptCacheConfig(anchor_messages=1))
    messages = [{"role": "user", "content": "hello world"}]

    result = injector.inject(messages)

    assert isinstance(result[0]["content"], list)
    block = result[0]["content"][0]
    assert block["type"] == "text"
    assert block["text"] == "hello world"
    assert block["cache_control"] == {"type": "ephemeral"}


def test_inject_string_content_does_not_mutate_original():
    """The original message list must not be mutated."""
    injector = PromptCacheInjector(PromptCacheConfig(anchor_messages=1))
    original_content = "hello world"
    messages = [{"role": "user", "content": original_content}]

    injector.inject(messages)

    assert messages[0]["content"] == original_content


# ---------------------------------------------------------------------------
# inject() — list content
# ---------------------------------------------------------------------------


def test_inject_list_content():
    """cache_control is added to the last block of a list-content message."""
    injector = PromptCacheInjector(PromptCacheConfig(anchor_messages=1))
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "first block"},
                {"type": "text", "text": "second block"},
            ],
        }
    ]

    result = injector.inject(messages)

    blocks = result[0]["content"]
    assert "cache_control" not in blocks[0]
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}


def test_inject_list_content_single_block():
    """Works correctly when the list has exactly one block."""
    injector = PromptCacheInjector(PromptCacheConfig(anchor_messages=1))
    messages = [{"role": "user", "content": [{"type": "text", "text": "only block"}]}]

    result = injector.inject(messages)

    assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# inject() — anchor count
# ---------------------------------------------------------------------------


def test_inject_anchors_n_messages():
    """Only the first anchor_messages messages receive cache_control."""
    n_total = 5
    n_anchor = 3
    injector = PromptCacheInjector(PromptCacheConfig(anchor_messages=n_anchor))
    messages = _make_messages(n_total)

    result = injector.inject(messages)

    for i, msg in enumerate(result):
        content = msg["content"]
        if i < n_anchor:
            # Must have been converted to list with cache_control
            assert isinstance(content, list), f"msg[{i}] should be a list"
            assert content[-1]["cache_control"] == {"type": "ephemeral"}, f"msg[{i}]"
        else:
            # Must remain a plain string (untouched)
            assert isinstance(content, str), f"msg[{i}] should remain a string"


def test_inject_zero_anchors():
    """anchor_messages=0 means no messages are modified."""
    injector = PromptCacheInjector(PromptCacheConfig(anchor_messages=0))
    messages = _make_messages(3)

    result = injector.inject(messages)

    for msg in result:
        assert isinstance(msg["content"], str)


# ---------------------------------------------------------------------------
# inject() — tool messages skipped
# ---------------------------------------------------------------------------


def test_inject_skips_tool_messages():
    """Messages with role='tool' are skipped; anchor quota is not consumed."""
    injector = PromptCacheInjector(PromptCacheConfig(anchor_messages=2))
    messages = [
        {"role": "tool", "content": "tool result"},
        {"role": "user", "content": "user msg 1"},
        {"role": "user", "content": "user msg 2"},
        {"role": "user", "content": "user msg 3"},
    ]

    result = injector.inject(messages)

    # tool message: untouched string
    assert isinstance(result[0]["content"], str)
    # first two non-tool messages get cache_control
    assert isinstance(result[1]["content"], list)
    assert result[1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(result[2]["content"], list)
    assert result[2]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # third non-tool message is beyond anchor quota
    assert isinstance(result[3]["content"], str)


def test_inject_all_tool_messages():
    """If all messages are tool role, none are modified."""
    injector = PromptCacheInjector(PromptCacheConfig(anchor_messages=3))
    messages = [{"role": "tool", "content": f"result {i}"} for i in range(3)]

    result = injector.inject(messages)

    for msg in result:
        assert isinstance(msg["content"], str)


# ---------------------------------------------------------------------------
# inject() — disabled mode
# ---------------------------------------------------------------------------


def test_inject_disabled_returns_deep_copy():
    """When disabled, inject() returns a deep copy without any modifications."""
    injector = PromptCacheInjector(PromptCacheConfig(enabled=False, anchor_messages=5))
    messages = _make_messages(3)

    result = injector.inject(messages)

    for msg in result:
        assert isinstance(msg["content"], str)
    # Verify it is a copy, not the same object
    assert result is not messages
    assert result[0] is not messages[0]


# ---------------------------------------------------------------------------
# inject_system()
# ---------------------------------------------------------------------------


def test_inject_system_prompt():
    """System prompt is wrapped in a cached text block list."""
    injector = PromptCacheInjector()
    system_text = "You are a helpful assistant."

    result = injector.inject_system(system_text)

    assert isinstance(result, list)
    assert len(result) == 1
    block = result[0]
    assert block["type"] == "text"
    assert block["text"] == system_text
    assert block["cache_control"] == {"type": "ephemeral"}


def test_inject_system_prompt_empty_string():
    """Empty system prompt is still wrapped correctly."""
    injector = PromptCacheInjector()
    result = injector.inject_system("")
    assert result[0]["text"] == ""
    assert result[0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# parse_cache_usage()
# ---------------------------------------------------------------------------


def test_parse_cache_usage():
    """Anthropic-style response body is parsed into CacheAwareTokenUsage."""
    response_body = {
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_read_input_tokens": 800,
            "cache_creation_input_tokens": 150,
        }
    }

    usage = parse_cache_usage(response_body)

    assert usage.prompt_tokens == 1000
    assert usage.completion_tokens == 200
    assert usage.total_tokens == 1200
    assert usage.cache_read_tokens == 800
    assert usage.cache_write_tokens == 150


def test_parse_cache_usage_no_cache_fields():
    """Missing cache fields default to zero."""
    response_body = {
        "usage": {
            "input_tokens": 500,
            "output_tokens": 100,
        }
    }

    usage = parse_cache_usage(response_body)

    assert usage.cache_read_tokens == 0
    assert usage.cache_write_tokens == 0


def test_parse_cache_usage_empty_body():
    """Completely empty response body yields all-zero usage."""
    usage = parse_cache_usage({})

    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.total_tokens == 0
    assert usage.cache_read_tokens == 0
    assert usage.cache_write_tokens == 0


# ---------------------------------------------------------------------------
# CacheAwareTokenUsage.effective_cost_multiplier()
# ---------------------------------------------------------------------------


def test_cache_aware_token_usage_cost_multiplier_no_cache():
    """Without any caching, multiplier should be exactly 1.0."""
    usage = CacheAwareTokenUsage(
        prompt_tokens=1000,
        completion_tokens=200,
        total_tokens=1200,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert usage.effective_cost_multiplier() == pytest.approx(1.0)


def test_cache_aware_token_usage_cost_multiplier_with_cache_hit():
    """Cache hits reduce effective cost; multiplier should be < 1.0."""
    usage = CacheAwareTokenUsage(
        prompt_tokens=1000,
        completion_tokens=200,
        total_tokens=1200,
        cache_read_tokens=800,  # 80% served from cache at 0.10x
        cache_write_tokens=0,
    )
    multiplier = usage.effective_cost_multiplier()
    assert multiplier < 1.0, f"Expected < 1.0, got {multiplier}"


def test_cache_aware_token_usage_cost_multiplier_full_cache_hit():
    """All prompt tokens from cache: multiplier should be ~0.10."""
    usage = CacheAwareTokenUsage(
        prompt_tokens=1000,
        completion_tokens=0,
        total_tokens=1000,
        cache_read_tokens=1000,
        cache_write_tokens=0,
    )
    multiplier = usage.effective_cost_multiplier()
    assert multiplier == pytest.approx(0.10, rel=1e-6)


def test_cache_aware_token_usage_cost_multiplier_cache_write_increases_cost():
    """Cache writes are more expensive (1.25x); multiplier should be > 1.0."""
    usage = CacheAwareTokenUsage(
        prompt_tokens=1000,
        completion_tokens=0,
        total_tokens=1000,
        cache_read_tokens=0,
        cache_write_tokens=1000,
    )
    multiplier = usage.effective_cost_multiplier()
    assert multiplier == pytest.approx(1.25, rel=1e-6)


# ---------------------------------------------------------------------------
# CacheAwareTokenUsage.cache_hit_rate()
# ---------------------------------------------------------------------------


def test_cache_hit_rate_zero():
    """No cache reads yields 0.0 hit rate."""
    usage = CacheAwareTokenUsage(1000, 100, 1100, 0, 0)
    assert usage.cache_hit_rate() == pytest.approx(0.0)


def test_cache_hit_rate_partial():
    """Partial cache reads yield a fractional hit rate."""
    usage = CacheAwareTokenUsage(1000, 100, 1100, 400, 0)
    assert usage.cache_hit_rate() == pytest.approx(0.4)


def test_cache_hit_rate_zero_prompt_tokens():
    """Zero prompt tokens should not cause division by zero."""
    usage = CacheAwareTokenUsage(0, 0, 0, 0, 0)
    assert usage.cache_hit_rate() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# PromptCacheStats
# ---------------------------------------------------------------------------


def test_prompt_cache_stats_update():
    """Statistics accumulate correctly across multiple update() calls."""
    stats = PromptCacheStats()

    # First request: no cache hit
    usage_no_hit = CacheAwareTokenUsage(500, 100, 600, 0, 0)
    stats.update(usage_no_hit)

    assert stats.total_requests == 1
    assert stats.cache_hits == 0
    assert stats.total_saved_tokens == 0

    # Second request: cache hit
    usage_hit = CacheAwareTokenUsage(1000, 200, 1200, 800, 0)
    stats.update(usage_hit)

    assert stats.total_requests == 2
    assert stats.cache_hits == 1
    assert stats.total_saved_tokens == 800

    # Third request: another cache hit
    usage_hit2 = CacheAwareTokenUsage(1000, 200, 1200, 600, 0)
    stats.update(usage_hit2)

    assert stats.total_requests == 3
    assert stats.cache_hits == 2
    assert stats.total_saved_tokens == 1400


def test_prompt_cache_stats_hit_rate():
    """hit_rate() reflects the fraction of requests with cache hits."""
    stats = PromptCacheStats()
    stats.update(CacheAwareTokenUsage(500, 100, 600, 500, 0))  # hit
    stats.update(CacheAwareTokenUsage(500, 100, 600, 0, 0))  # miss
    stats.update(CacheAwareTokenUsage(500, 100, 600, 300, 0))  # hit

    assert stats.hit_rate() == pytest.approx(2 / 3)


def test_prompt_cache_stats_hit_rate_no_requests():
    """hit_rate() returns 0.0 when no requests have been recorded."""
    stats = PromptCacheStats()
    assert stats.hit_rate() == pytest.approx(0.0)


def test_prompt_cache_stats_initial_state():
    """PromptCacheStats starts with all-zero fields."""
    stats = PromptCacheStats()
    assert stats.total_requests == 0
    assert stats.cache_hits == 0
    assert stats.total_saved_tokens == 0
