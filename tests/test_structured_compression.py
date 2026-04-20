"""Tests for hi_agent.memory.structured_compression.

Covers:
- MessagePartitioner head/tail/middle partitioning
- StructuredSummary.to_context_block()
- StructuredSummary.merge()
- StructuredSummary serialization round-trip
- StructuredCompressor LLM interaction (mock)
- StructuredCompressor incremental (existing_summary) path
- _parse_llm_response: valid JSON and fallback
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio  # noqa: F401 - ensures the plugin is imported
from hi_agent.llm import LLMResponse, TokenUsage
from hi_agent.memory.structured_compression import (
    MessagePartitioner,
    StructuredCompressor,
    StructuredCompressorConfig,
    StructuredSummary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_messages(count: int, role: str = "user") -> list[dict]:
    return [{"role": role, "content": f"Message {i}"} for i in range(count)]


def _make_mixed_messages(count: int) -> list[dict]:
    """Alternate user / assistant messages."""
    roles = ["user", "assistant"]
    return [{"role": roles[i % 2], "content": f"Message {i} content here"} for i in range(count)]


_SENTINEL = object()


def _sample_summary(
    goal: str = "Sample goal",
    progress: str = "Done A",
    decisions: str = "Chose X",
    modified_files: list[str] | None = _SENTINEL,  # type: ignore[assignment]
    next_steps: str = "Do B",
    source_message_count: int = 5,
) -> StructuredSummary:
    if modified_files is _SENTINEL:
        modified_files = ["file_a.py"]
    return StructuredSummary(
        goal=goal,
        progress=progress,
        decisions=decisions,
        modified_files=list(modified_files),  # type: ignore[arg-type]
        next_steps=next_steps,
        compressed_at="2026-04-10T00:00:00+00:00",
        source_message_count=source_message_count,
    )


def _mock_llm_gateway(response_content: str) -> MagicMock:
    """Create a mock AsyncLLMGateway that returns the given content."""
    gateway = MagicMock()
    gateway.complete = AsyncMock(
        return_value=LLMResponse(
            content=response_content,
            model="mock-light",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )
    )
    return gateway


# ---------------------------------------------------------------------------
# 1. test_message_partitioner_head_tail
# ---------------------------------------------------------------------------


def test_message_partitioner_head_tail():
    """Head and tail are protected; middle contains the remaining messages."""
    messages = _make_mixed_messages(20)
    partitioner = MessagePartitioner(head_count=3, tail_token_budget=200)
    section = partitioner.partition(messages)

    # Head is exactly the first 3 messages
    assert section.head_messages == messages[:3]

    # Tail + middle together cover messages[3:]
    reconstructed = section.middle_messages + section.tail_messages
    assert reconstructed == messages[3:]

    # Middle is non-empty (there are 17 remaining messages)
    assert len(section.middle_messages) > 0

    # Tail is non-empty (budget 200 chars covers a few short messages)
    assert len(section.tail_messages) > 0

    # No message appears in both middle and tail
    middle_set = {id(m) for m in section.middle_messages}
    tail_set = {id(m) for m in section.tail_messages}
    assert middle_set.isdisjoint(tail_set)


# ---------------------------------------------------------------------------
# 2. test_message_partitioner_small_list
# ---------------------------------------------------------------------------


def test_message_partitioner_small_list():
    """When there are fewer messages than head_count, all go to head."""
    messages = _make_messages(2)
    partitioner = MessagePartitioner(head_count=5, tail_token_budget=8000)
    section = partitioner.partition(messages)

    assert section.head_messages == messages
    assert section.middle_messages == []
    assert section.tail_messages == []


def test_message_partitioner_exactly_head_count():
    """Exactly head_count messages → all in head, nothing in middle/tail."""
    messages = _make_messages(3)
    partitioner = MessagePartitioner(head_count=3, tail_token_budget=8000)
    section = partitioner.partition(messages)

    assert section.head_messages == messages
    assert section.middle_messages == []
    assert section.tail_messages == []


def test_message_partitioner_zero_tail_budget():
    """With tail_token_budget=0, tail is empty and all remaining go to middle."""
    messages = _make_messages(6)
    partitioner = MessagePartitioner(head_count=2, tail_token_budget=0)
    section = partitioner.partition(messages)

    assert section.head_messages == messages[:2]
    assert section.middle_messages == messages[2:]
    assert section.tail_messages == []


# ---------------------------------------------------------------------------
# 3. test_structured_summary_to_context_block
# ---------------------------------------------------------------------------


def test_structured_summary_to_context_block():
    """Context block contains all five fields in expected format."""
    summary = _sample_summary(
        goal="Build the feature",
        progress="Completed design",
        decisions="Chose asyncio",
        modified_files=["a.py", "b.py"],
        next_steps="Write tests",
    )
    block = summary.to_context_block()

    assert "[CONTEXT COMPACTION" in block
    assert "目标: Build the feature" in block
    assert "进度: Completed design" in block
    assert "关键决策: Chose asyncio" in block
    assert "a.py" in block
    assert "b.py" in block
    assert "下一步: Write tests" in block
    assert "[END COMPACTION" in block
    assert "5" in block  # source_message_count


def test_structured_summary_to_context_block_no_files():
    """When modified_files is empty, context block shows placeholder."""
    summary = _sample_summary(modified_files=[])
    block = summary.to_context_block()
    assert "(无)" in block


# ---------------------------------------------------------------------------
# 4. test_structured_summary_merge
# ---------------------------------------------------------------------------


def test_structured_summary_merge():
    """Merge: goal is immutable, progress is concatenated, files are deduped."""
    older = _sample_summary(
        goal="Original goal",
        progress="Step 1 done",
        decisions="Decision A",
        modified_files=["shared.py", "old_only.py"],
        next_steps="Old next step",
        source_message_count=5,
    )
    newer = _sample_summary(
        goal="New goal (should be ignored)",
        progress="Step 2 done",
        decisions="Decision B",
        modified_files=["shared.py", "new_only.py"],
        next_steps="New next step",
        source_message_count=3,
    )

    merged = older.merge(newer)

    # Goal is preserved from the older summary
    assert merged.goal == "Original goal"

    # Progress combines both (older first, newer second)
    assert "Step 1 done" in merged.progress
    assert "Step 2 done" in merged.progress
    assert "之前:" in merged.progress
    assert "新增:" in merged.progress

    # Decisions are appended
    assert "Decision A" in merged.decisions
    assert "Decision B" in merged.decisions

    # Files: union, shared.py appears once
    assert merged.modified_files.count("shared.py") == 1
    assert "old_only.py" in merged.modified_files
    assert "new_only.py" in merged.modified_files

    # Next steps come from newer
    assert merged.next_steps == "New next step"

    # Source message count is summed
    assert merged.source_message_count == 8

    # compressed_at comes from newer
    assert merged.compressed_at == newer.compressed_at


# ---------------------------------------------------------------------------
# 5. test_structured_summary_serialization
# ---------------------------------------------------------------------------


def test_structured_summary_serialization():
    """to_dict / from_dict round-trip preserves all fields."""
    original = _sample_summary(
        goal="Test goal",
        progress="50% done",
        decisions="Use JSON schema",
        modified_files=["x.py", "y.py"],
        next_steps="Deploy",
        source_message_count=12,
    )
    d = original.to_dict()
    restored = StructuredSummary.from_dict(d)

    assert restored.goal == original.goal
    assert restored.progress == original.progress
    assert restored.decisions == original.decisions
    assert restored.modified_files == original.modified_files
    assert restored.next_steps == original.next_steps
    assert restored.compressed_at == original.compressed_at
    assert restored.source_message_count == original.source_message_count


def test_structured_summary_serialization_is_json_compatible():
    """to_dict result must be JSON-serializable without error."""
    summary = _sample_summary()
    d = summary.to_dict()
    # Should not raise
    json_str = json.dumps(d)
    reparsed = json.loads(json_str)
    restored = StructuredSummary.from_dict(reparsed)
    assert restored.goal == summary.goal


# ---------------------------------------------------------------------------
# 6. test_structured_compressor_calls_llm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_compressor_calls_llm():
    """StructuredCompressor must call the LLM and return a StructuredSummary."""
    llm_response_json = json.dumps({
        "goal": "LLM goal",
        "progress": "LLM progress",
        "decisions": "LLM decision",
        "modified_files": ["llm_file.py"],
        "next_steps": "LLM next",
    })
    gateway = _mock_llm_gateway(llm_response_json)
    config = StructuredCompressorConfig(head_count=1, tail_token_budget=50)
    compressor = StructuredCompressor(llm=gateway, config=config)

    # 10 messages: head(1) + middle + tail
    messages = _make_mixed_messages(10)
    _, summary = await compressor.compress(messages, existing_summary=None)

    # LLM was called exactly once
    gateway.complete.assert_awaited_once()

    # Summary fields match what the LLM returned
    assert summary.goal == "LLM goal"
    assert summary.progress == "LLM progress"
    assert summary.decisions == "LLM decision"
    assert summary.modified_files == ["llm_file.py"]
    assert summary.next_steps == "LLM next"
    assert summary.source_message_count > 0


# ---------------------------------------------------------------------------
# 7. test_structured_compressor_returns_compressed_messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_compressor_returns_compressed_messages():
    """Returned message list = [injection] + head + tail; middle is gone."""
    llm_response_json = json.dumps({
        "goal": "G",
        "progress": "P",
        "decisions": "D",
        "modified_files": [],
        "next_steps": "N",
    })
    gateway = _mock_llm_gateway(llm_response_json)
    config = StructuredCompressorConfig(head_count=2, tail_token_budget=100)
    compressor = StructuredCompressor(llm=gateway, config=config)

    # 10 messages — head=2, some tail, some middle
    messages = _make_mixed_messages(10)
    new_messages, _ = await compressor.compress(messages)

    # First message is the summary injection (system role)
    assert new_messages[0]["role"] == "system"
    assert "[CONTEXT COMPACTION" in new_messages[0]["content"]

    # Second and third messages are head
    assert new_messages[1] == messages[0]
    assert new_messages[2] == messages[1]

    # Total count < original (middle messages were removed)
    assert len(new_messages) < len(messages)


# ---------------------------------------------------------------------------
# 8. test_structured_compressor_incremental_update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_compressor_incremental_update():
    """With existing_summary, goal is preserved and progress is accumulated."""
    existing = _sample_summary(
        goal="Original goal",
        progress="Phase 1",
        decisions="Decision A",
        modified_files=["base.py"],
        next_steps="Phase 2",
        source_message_count=5,
    )

    # LLM returns incremental info
    llm_response_json = json.dumps({
        "goal": "Should be ignored in merge",
        "progress": "Phase 2 complete",
        "decisions": "Decision B",
        "modified_files": ["new.py"],
        "next_steps": "Phase 3",
    })
    gateway = _mock_llm_gateway(llm_response_json)
    config = StructuredCompressorConfig(head_count=1, tail_token_budget=50)
    compressor = StructuredCompressor(llm=gateway, config=config)

    messages = _make_mixed_messages(10)
    _, merged_summary = await compressor.compress(
        messages, existing_summary=existing
    )

    # Original goal is preserved through the merge
    assert merged_summary.goal == "Original goal"

    # Progress accumulates
    assert "Phase 1" in merged_summary.progress
    assert "Phase 2 complete" in merged_summary.progress

    # Files are merged
    assert "base.py" in merged_summary.modified_files
    assert "new.py" in merged_summary.modified_files

    # Next steps from latest summary
    assert merged_summary.next_steps == "Phase 3"


# ---------------------------------------------------------------------------
# 9. test_parse_llm_response_valid_json
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_llm_response_valid_json():
    """Valid JSON response is parsed into a correct StructuredSummary."""
    gateway = _mock_llm_gateway("")  # content overridden below
    config = StructuredCompressorConfig()
    compressor = StructuredCompressor(llm=gateway, config=config)

    response_json = json.dumps({
        "goal": "Parse test goal",
        "progress": "Parsed progress",
        "decisions": "Parsed decision",
        "modified_files": ["parsed.py"],
        "next_steps": "Parsed next",
    })
    fallback_messages = _make_messages(3)

    summary = compressor._parse_llm_response(response_json, fallback_messages)

    assert summary.goal == "Parse test goal"
    assert summary.progress == "Parsed progress"
    assert summary.decisions == "Parsed decision"
    assert summary.modified_files == ["parsed.py"]
    assert summary.next_steps == "Parsed next"
    assert summary.source_message_count == 3


def test_parse_llm_response_valid_json_with_code_fence():
    """JSON wrapped in markdown code fences is correctly parsed."""
    gateway = _mock_llm_gateway("")
    compressor = StructuredCompressor(llm=gateway, config=StructuredCompressorConfig())

    response_with_fence = (
        "```json\n"
        + json.dumps({
            "goal": "Fenced goal",
            "progress": "Fenced progress",
            "decisions": "Fenced decision",
            "modified_files": [],
            "next_steps": "Fenced next",
        })
        + "\n```"
    )
    summary = compressor._parse_llm_response(response_with_fence, [])
    assert summary.goal == "Fenced goal"


# ---------------------------------------------------------------------------
# 10. test_parse_llm_response_invalid_json_fallback
# ---------------------------------------------------------------------------


def test_parse_llm_response_invalid_json_fallback():
    """When LLM returns invalid JSON, the fallback minimal summary is used."""
    gateway = _mock_llm_gateway("")
    compressor = StructuredCompressor(llm=gateway, config=StructuredCompressorConfig())

    bad_response = "Sorry, I cannot generate JSON right now."
    fallback_messages = [
        {"role": "user", "content": "My goal is to fix bug #42"},
        {"role": "assistant", "content": "I found the issue"},
    ]

    summary = compressor._parse_llm_response(bad_response, fallback_messages)

    # Fallback: goal extracted from first user message
    assert "bug #42" in summary.goal or summary.goal  # non-empty
    assert summary.source_message_count == 2
    assert isinstance(summary.modified_files, list)
    assert isinstance(summary.compressed_at, str)


@pytest.mark.asyncio
async def test_structured_compressor_llm_exception_uses_fallback():
    """When LLM raises an exception, compress() returns a fallback summary."""
    gateway = MagicMock()
    gateway.complete = AsyncMock(side_effect=RuntimeError("Network error"))
    config = StructuredCompressorConfig(head_count=1, tail_token_budget=50)
    compressor = StructuredCompressor(llm=gateway, config=config)

    messages = _make_mixed_messages(8)
    # Should not raise
    new_messages, summary = await compressor.compress(messages)

    assert isinstance(summary, StructuredSummary)
    assert isinstance(new_messages, list)


# ---------------------------------------------------------------------------
# Bonus: estimate_chars
# ---------------------------------------------------------------------------


def test_estimate_chars_string_content():
    partitioner = MessagePartitioner()
    msg = {"role": "user", "content": "hello world"}
    assert partitioner.estimate_chars(msg) == len("hello world")


def test_estimate_chars_list_content():
    partitioner = MessagePartitioner()
    msg = {
        "role": "assistant",
        "content": [{"text": "Part A"}, {"text": " Part B"}],
    }
    assert partitioner.estimate_chars(msg) == len("Part A") + len(" Part B")


def test_estimate_chars_empty():
    partitioner = MessagePartitioner()
    msg = {"role": "user", "content": ""}
    assert partitioner.estimate_chars(msg) == 0
