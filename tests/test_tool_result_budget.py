"""Tests for hi_agent.task_view.result_budget."""

from __future__ import annotations

from hi_agent.task_view.result_budget import (
    ToolResultBudget,
    ToolResultBudgetConfig,
    ToolResultBudgetState,
    TruncatedResult,
    create_tool_result_budget,
    estimate_chars,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_budget(
    max_single: int = 32_000,
    max_cumulative: int = 128_000,
) -> ToolResultBudget:
    """Return a fresh ToolResultBudget with the given limits."""
    config = ToolResultBudgetConfig(
        max_single_result_chars=max_single,
        max_cumulative_chars=max_cumulative,
    )
    state = ToolResultBudgetState()
    return ToolResultBudget(config=config, state=state)


# ---------------------------------------------------------------------------
# 1. Small result passes through unchanged
# ---------------------------------------------------------------------------


def test_small_result_passes_through() -> None:
    budget = _make_budget(max_single=100)
    result = budget.process("read_file", "hello world")
    assert result == "hello world"


def test_small_result_updates_state() -> None:
    budget = _make_budget(max_single=100)
    budget.process("read_file", "hello")
    assert budget.get_state().cumulative_chars_used == len("hello")
    assert budget.get_state().truncation_count == 0


# ---------------------------------------------------------------------------
# 2. Large result is truncated
# ---------------------------------------------------------------------------


def test_large_result_truncated() -> None:
    budget = _make_budget(max_single=10)
    big_content = "x" * 100
    result = budget.process("search", big_content)
    assert result != big_content
    assert "[TRUNCATED" in result


def test_large_result_truncation_increments_counter() -> None:
    budget = _make_budget(max_single=10)
    budget.process("search", "x" * 100)
    assert budget.get_state().truncation_count == 1


# ---------------------------------------------------------------------------
# 3. Placeholder format is correct
# ---------------------------------------------------------------------------


def test_truncated_placeholder_format() -> None:
    budget = _make_budget(max_single=5)
    content = "abcdefghij"  # 10 chars > 5 limit
    placeholder = budget.process("my_tool", content)
    assert "tool=my_tool" in placeholder
    assert f"size={len(content)}chars" in placeholder
    # hash must be present (16-char hex prefix)
    import re
    assert re.search(r"hash=[0-9a-f]{16}", placeholder)


def test_truncated_result_to_placeholder_format() -> None:
    tr = TruncatedResult(
        original_chars=500,
        content_hash="abcdef1234567890",
        tool_name="grep",
        marker="[TRUNCATED]",
    )
    ph = tr.to_placeholder()
    assert ph == "[TRUNCATED: tool=grep, size=500chars, hash=abcdef1234567890]"


# ---------------------------------------------------------------------------
# 4. Cumulative budget tracking
# ---------------------------------------------------------------------------


def test_cumulative_budget_tracking() -> None:
    # Each result is 60 chars, single limit is 100, cumulative is 100.
    # First result (60 chars) fits. Second result would bring total to 120 >
    # 100, so it must be truncated.
    budget = _make_budget(max_single=100, max_cumulative=100)
    first = budget.process("tool_a", "a" * 60)
    assert first == "a" * 60  # passed through

    second = budget.process("tool_b", "b" * 60)
    assert "[TRUNCATED" in second  # cumulative budget exhausted


def test_cumulative_tracks_across_multiple_results() -> None:
    budget = _make_budget(max_single=50, max_cumulative=200)
    for _ in range(4):
        budget.process("t", "x" * 50)
    # 4 × 50 = 200, all should fit
    assert budget.get_state().truncation_count == 0
    assert budget.get_state().cumulative_chars_used == 200

    # 5th result tips over
    result = budget.process("t", "x" * 1)
    assert "[TRUNCATED" in result


# ---------------------------------------------------------------------------
# 5. process_message_results handles tool messages
# ---------------------------------------------------------------------------


def test_process_message_results() -> None:
    budget = _make_budget(max_single=10)
    messages = [
        {"role": "user", "content": "What is the weather?"},
        {"role": "assistant", "content": "Let me check."},
        {
            "role": "tool",
            "name": "weather_api",
            "content": "x" * 200,  # exceeds limit
        },
    ]
    processed = budget.process_message_results(messages)
    assert len(processed) == 3
    # user and assistant untouched
    assert processed[0]["content"] == "What is the weather?"
    assert processed[1]["content"] == "Let me check."
    # tool result truncated
    assert "[TRUNCATED" in processed[2]["content"]


def test_process_message_results_small_tool_content() -> None:
    budget = _make_budget(max_single=1000)
    messages = [
        {"role": "tool", "name": "echo", "content": "short result"},
    ]
    processed = budget.process_message_results(messages)
    assert processed[0]["content"] == "short result"


def test_process_message_results_list_content_blocks() -> None:
    """Tool message whose content is a list of blocks."""
    budget = _make_budget(max_single=5)
    messages = [
        {
            "role": "tool",
            "name": "reader",
            "content": [
                {"type": "text", "text": "abcdefghij"},  # 10 > 5
                {"type": "image_url", "url": "http://example.com/img.png"},
            ],
        }
    ]
    processed = budget.process_message_results(messages)
    blocks = processed[0]["content"]
    assert isinstance(blocks, list)
    # text block should be truncated
    assert "[TRUNCATED" in blocks[0]["text"]
    # image block untouched
    assert blocks[1]["type"] == "image_url"


# ---------------------------------------------------------------------------
# 6. State serialisation round-trip
# ---------------------------------------------------------------------------


def test_state_serialization() -> None:
    state = ToolResultBudgetState(cumulative_chars_used=1234, truncation_count=7)
    d = state.to_dict()
    restored = ToolResultBudgetState.from_dict(d)
    assert restored.cumulative_chars_used == 1234
    assert restored.truncation_count == 7


def test_state_serialization_defaults() -> None:
    state = ToolResultBudgetState()
    d = state.to_dict()
    restored = ToolResultBudgetState.from_dict(d)
    assert restored.cumulative_chars_used == 0
    assert restored.truncation_count == 0


def test_state_from_dict_missing_keys() -> None:
    """from_dict must handle partial / empty dicts gracefully."""
    restored = ToolResultBudgetState.from_dict({})
    assert restored.cumulative_chars_used == 0
    assert restored.truncation_count == 0


# ---------------------------------------------------------------------------
# 7. Non-tool messages are not touched
# ---------------------------------------------------------------------------


def test_non_tool_messages_untouched() -> None:
    budget = _make_budget(max_single=5)
    messages = [
        {"role": "user", "content": "x" * 1000},
        {"role": "assistant", "content": "y" * 1000},
        {"role": "system", "content": "z" * 1000},
    ]
    processed = budget.process_message_results(messages)
    for orig, proc in zip(messages, processed):
        assert orig["content"] == proc["content"]
    assert budget.get_state().truncation_count == 0
    assert budget.get_state().cumulative_chars_used == 0


# ---------------------------------------------------------------------------
# 8. Empty result is not truncated
# ---------------------------------------------------------------------------


def test_empty_result_no_truncation() -> None:
    budget = _make_budget(max_single=10)
    result = budget.process("tool", "")
    assert result == ""
    assert budget.get_state().truncation_count == 0
    assert budget.get_state().cumulative_chars_used == 0


# ---------------------------------------------------------------------------
# estimate_chars helper
# ---------------------------------------------------------------------------


def test_estimate_chars_str() -> None:
    assert estimate_chars("hello") == 5


def test_estimate_chars_list() -> None:
    assert estimate_chars(["ab", "cde"]) == 5


def test_estimate_chars_dict() -> None:
    d = {"key": "val"}
    assert estimate_chars(d) == len(str(d))


def test_estimate_chars_nested_list() -> None:
    assert estimate_chars(["a", ["bb", "ccc"]]) == 6


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def test_create_tool_result_budget_defaults() -> None:
    b = create_tool_result_budget()
    assert isinstance(b, ToolResultBudget)
    cfg = b._config
    assert cfg.max_single_result_chars == 32_000
    assert cfg.max_cumulative_chars == 128_000


def test_create_tool_result_budget_custom() -> None:
    b = create_tool_result_budget(
        {"max_single_result_chars": 500, "max_cumulative_chars": 2000}
    )
    cfg = b._config
    assert cfg.max_single_result_chars == 500
    assert cfg.max_cumulative_chars == 2000


def test_create_tool_result_budget_ignores_unknown_keys() -> None:
    b = create_tool_result_budget({"unknown_key": 999, "max_single_result_chars": 100})
    cfg = b._config
    assert cfg.max_single_result_chars == 100


# ---------------------------------------------------------------------------
# Deep copy — original messages not mutated
# ---------------------------------------------------------------------------


def test_process_message_results_does_not_mutate_originals() -> None:
    budget = _make_budget(max_single=5)
    original_content = "x" * 200
    messages = [{"role": "tool", "name": "t", "content": original_content}]
    budget.process_message_results(messages)
    # Original list element must be unchanged
    assert messages[0]["content"] == original_content
