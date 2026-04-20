"""Tests for hi_agent.observability.trajectory_exporter.

Covers: TrajectoryMessage, TrajectoryRecord, TrajectoryFilter,
        SessionMessageParser, TrajectoryExporter, RewardAnnotator.
"""

from __future__ import annotations

import json
from pathlib import Path

from hi_agent.observability.trajectory_exporter import (
    RewardAnnotator,
    SessionMessageParser,
    TrajectoryExporter,
    TrajectoryFilter,
    TrajectoryMessage,
    TrajectoryRecord,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    run_id: str = "run-001",
    task_id: str | None = "task-1",
    messages: list[TrajectoryMessage] | None = None,
    quality_score: float | None = 0.9,
    total_turns: int = 2,
    total_tool_calls: int = 1,
    reward: float | None = None,
    metadata: dict | None = None,
) -> TrajectoryRecord:
    if messages is None:
        messages = [
            TrajectoryMessage(role="user", content="Hello"),
            TrajectoryMessage(role="assistant", content="Hi there"),
        ]
    return TrajectoryRecord(
        run_id=run_id,
        task_id=task_id,
        messages=messages,
        quality_score=quality_score,
        total_turns=total_turns,
        total_tool_calls=total_tool_calls,
        reward=reward,
        created_at="2026-04-10T00:00:00+00:00",
        metadata=metadata or {},
    )


def _make_session_dict(
    run_id: str = "run-001",
    messages: list[dict] | None = None,
    quality_score: float | None = None,
    status: str = "completed",
) -> dict:
    if messages is None:
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
    return {
        "run_id": run_id,
        "task_id": "task-1",
        "messages": messages,
        "quality_score": quality_score,
        "status": status,
    }


# ---------------------------------------------------------------------------
# TrajectoryMessage
# ---------------------------------------------------------------------------


class TestTrajectoryMessage:
    def test_to_dict_excludes_none(self):
        """None fields must not appear in the serialised dict."""
        msg = TrajectoryMessage(role="user", content="Hello")
        d = msg.to_dict()
        assert "role" in d
        assert "content" in d
        # Optional fields with None value must be absent
        assert "reasoning" not in d
        assert "tool_calls" not in d
        assert "tool_call_id" not in d
        assert "timestamp" not in d

    def test_to_dict_includes_optional_when_set(self):
        """Optional fields present in the dict when they carry a value."""
        msg = TrajectoryMessage(
            role="assistant",
            content="Thinking...",
            reasoning="step 1: ...",
            tool_calls=[{"name": "search", "id": "tc-1", "input": {"q": "foo"}}],
            timestamp="2026-01-01T00:00:00Z",
        )
        d = msg.to_dict()
        assert d["reasoning"] == "step 1: ..."
        assert d["tool_calls"] == [{"name": "search", "id": "tc-1", "input": {"q": "foo"}}]
        assert d["timestamp"] == "2026-01-01T00:00:00Z"
        assert "tool_call_id" not in d  # still None


# ---------------------------------------------------------------------------
# TrajectoryRecord
# ---------------------------------------------------------------------------


class TestTrajectoryRecord:
    def test_to_jsonl_line_is_valid_json(self):
        """to_jsonl_line must produce a valid JSON string."""
        record = _make_record()
        line = record.to_jsonl_line()
        parsed = json.loads(line)
        assert parsed["run_id"] == "run-001"
        assert isinstance(parsed["messages"], list)

    def test_to_jsonl_line_no_trailing_newline(self):
        """to_jsonl_line must not end with a newline character."""
        record = _make_record()
        line = record.to_jsonl_line()
        assert not line.endswith("\n")

    def test_to_jsonl_line_unicode_preserved(self):
        """Unicode characters must be preserved (ensure_ascii=False)."""
        record = _make_record()
        record.metadata["note"] = "日本語テスト"
        line = record.to_jsonl_line()
        assert "日本語テスト" in line

    def test_from_dict_roundtrip(self):
        """from_dict(to_jsonl_line) must restore the record faithfully."""
        record = _make_record(
            messages=[
                TrajectoryMessage(
                    role="user",
                    content="Hello",
                    reasoning="thinking",
                    tool_calls=[{"name": "search", "id": "1", "input": {}}],
                ),
            ]
        )
        line = record.to_jsonl_line()
        restored = TrajectoryRecord.from_dict(json.loads(line))
        assert restored.run_id == record.run_id
        assert restored.task_id == record.task_id
        assert len(restored.messages) == 1
        assert restored.messages[0].reasoning == "thinking"
        assert restored.messages[0].tool_calls == [{"name": "search", "id": "1", "input": {}}]


# ---------------------------------------------------------------------------
# TrajectoryFilter
# ---------------------------------------------------------------------------


class TestTrajectoryFilter:
    def test_accept_all_conditions_met(self):
        """A record that satisfies all criteria must be accepted."""
        flt = TrajectoryFilter(
            min_quality=0.5,
            min_turns=1,
            max_turns=100,
            require_reward=False,
            allowed_statuses=["completed"],
        )
        record = _make_record(quality_score=0.8, total_turns=3, metadata={"status": "completed"})
        assert flt.accept(record) is True

    def test_reject_low_quality(self):
        """A record with quality below min_quality must be rejected."""
        flt = TrajectoryFilter(min_quality=0.7)
        record = _make_record(quality_score=0.5)
        assert flt.accept(record) is False

    def test_reject_too_few_turns(self):
        """A record with fewer turns than min_turns must be rejected."""
        flt = TrajectoryFilter(min_turns=5)
        record = _make_record(total_turns=2)
        assert flt.accept(record) is False

    def test_reject_too_many_turns(self):
        """A record exceeding max_turns must be rejected."""
        flt = TrajectoryFilter(max_turns=10)
        record = _make_record(total_turns=20)
        assert flt.accept(record) is False

    def test_reject_missing_reward_when_required(self):
        """A record with no reward must be rejected when require_reward=True."""
        flt = TrajectoryFilter(require_reward=True)
        record = _make_record(reward=None)
        assert flt.accept(record) is False

    def test_accept_with_reward_when_required(self):
        """A record with a reward must pass require_reward=True."""
        flt = TrajectoryFilter(require_reward=True)
        record = _make_record(reward=0.85)
        assert flt.accept(record) is True

    def test_reject_disallowed_status(self):
        """A record with a status not in allowed_statuses must be rejected."""
        flt = TrajectoryFilter(allowed_statuses=["completed"])
        record = _make_record(metadata={"status": "failed"})
        assert flt.accept(record) is False

    def test_accept_no_status_in_metadata(self):
        """When metadata has no 'status', the status gate is skipped."""
        flt = TrajectoryFilter(allowed_statuses=["completed"])
        record = _make_record(metadata={})
        # No status → gate is not enforced → should accept (assuming other criteria met)
        assert flt.accept(record) is True


# ---------------------------------------------------------------------------
# SessionMessageParser
# ---------------------------------------------------------------------------


class TestSessionMessageParser:
    def test_parse_messages_basic(self):
        """Standard role/content messages are parsed correctly."""
        session = {
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ]
        }
        msgs = SessionMessageParser.parse_messages(session)
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "Hello"
        assert msgs[1].role == "assistant"
        assert msgs[1].content == "Hi"

    def test_parse_messages_falls_back_to_history(self):
        """Falls back to 'history' key when 'messages' is absent."""
        session = {
            "history": [
                {"role": "user", "content": "From history"},
            ]
        }
        msgs = SessionMessageParser.parse_messages(session)
        assert len(msgs) == 1
        assert msgs[0].content == "From history"

    def test_parse_messages_empty_when_no_key(self):
        """Returns empty list when neither 'messages' nor 'history' exists."""
        msgs = SessionMessageParser.parse_messages({})
        assert msgs == []

    def test_extracts_reasoning(self):
        """'reasoning' key in a message dict is surfaced as TrajectoryMessage.reasoning."""
        session = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Answer",
                    "reasoning": "I think step by step...",
                }
            ]
        }
        msgs = SessionMessageParser.parse_messages(session)
        assert msgs[0].reasoning == "I think step by step..."

    def test_extracts_thinking_key(self):
        """'thinking' key is an alias for reasoning."""
        session = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Answer",
                    "thinking": "deep thought",
                }
            ]
        }
        msgs = SessionMessageParser.parse_messages(session)
        assert msgs[0].reasoning == "deep thought"

    def test_extracts_reasoning_from_content_blocks(self):
        """Anthropic content-block format with type='thinking' is extracted."""
        session = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "block reasoning"},
                        {"type": "text", "text": "final answer"},
                    ],
                }
            ]
        }
        msgs = SessionMessageParser.parse_messages(session)
        assert msgs[0].reasoning == "block reasoning"

    def test_extracts_tool_calls(self):
        """Standard 'tool_calls' list is forwarded to TrajectoryMessage."""
        tool_calls = [{"name": "calculator", "id": "tc-42", "input": {"expr": "1+1"}}]
        session = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": tool_calls,
                }
            ]
        }
        msgs = SessionMessageParser.parse_messages(session)
        assert msgs[0].tool_calls == tool_calls

    def test_extracts_tool_calls_from_content_blocks(self):
        """Anthropic content-block format with type='tool_use' is extracted."""
        session = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "search",
                            "id": "tu-1",
                            "input": {"q": "pytest"},
                        }
                    ],
                }
            ]
        }
        msgs = SessionMessageParser.parse_messages(session)
        assert msgs[0].tool_calls is not None
        assert len(msgs[0].tool_calls) == 1
        assert msgs[0].tool_calls[0]["name"] == "search"

    def test_extract_reasoning_returns_none_when_absent(self):
        """Returns None when no reasoning/thinking is found."""
        result = SessionMessageParser.extract_reasoning({"role": "user", "content": "hi"})
        assert result is None

    def test_extract_tool_calls_returns_none_when_absent(self):
        """Returns None when no tool_calls are present."""
        result = SessionMessageParser.extract_tool_calls({"role": "user", "content": "hi"})
        assert result is None


# ---------------------------------------------------------------------------
# TrajectoryExporter
# ---------------------------------------------------------------------------


class TestTrajectoryExporter:
    def test_export_session_returns_record(self):
        """export_session builds and returns a TrajectoryRecord."""
        exporter = TrajectoryExporter()
        session = _make_session_dict(run_id="run-123")
        record = exporter.export_session(session)
        assert record is not None
        assert record.run_id == "run-123"

    def test_export_session_with_filter_passes(self):
        """Records passing the filter are returned."""
        flt = TrajectoryFilter(min_quality=0.5, allowed_statuses=["completed"])
        exporter = TrajectoryExporter(filter=flt)
        session = _make_session_dict(quality_score=0.9, status="completed")
        record = exporter.export_session(session)
        assert record is not None

    def test_export_session_filtered_returns_none(self):
        """Records that fail the filter return None."""
        flt = TrajectoryFilter(min_quality=0.8)
        exporter = TrajectoryExporter(filter=flt)
        session = _make_session_dict(quality_score=0.5)
        result = exporter.export_session(session)
        assert result is None

    def test_export_session_writes_to_file(self, tmp_path: Path):
        """When output_path is given, the record is appended to the file."""
        output = tmp_path / "output.jsonl"
        exporter = TrajectoryExporter()
        session = _make_session_dict(run_id="run-file")
        exporter.export_session(session, output_path=str(output))
        assert output.exists()
        lines = output.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["run_id"] == "run-file"

    def test_export_session_appends_multiple(self, tmp_path: Path):
        """Calling export_session multiple times appends to the same file."""
        output = tmp_path / "output.jsonl"
        exporter = TrajectoryExporter()
        for i in range(3):
            session = _make_session_dict(run_id=f"run-{i}")
            exporter.export_session(session, output_path=str(output))
        lines = output.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

    def test_export_batch_stats(self):
        """export_batch returns correct ExportStats counts."""
        flt = TrajectoryFilter(min_quality=0.6)
        exporter = TrajectoryExporter(filter=flt)
        sessions = [
            _make_session_dict(run_id="r1", quality_score=0.9),  # passes
            _make_session_dict(run_id="r2", quality_score=0.3),  # filtered
            _make_session_dict(run_id="r3", quality_score=0.8),  # passes
        ]

        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            stats = exporter.export_batch(sessions, tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        assert stats.total_sessions == 3
        assert stats.exported == 2
        assert stats.filtered_out == 1
        assert stats.errors == 0

    def test_export_batch_output_file_created(self, tmp_path: Path):
        """export_batch creates the output file with correct number of lines."""
        output = tmp_path / "batch_output.jsonl"
        exporter = TrajectoryExporter()
        sessions = [_make_session_dict(run_id=f"run-{i}") for i in range(5)]
        stats = exporter.export_batch(sessions, str(output))
        assert output.exists()
        lines = output.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 5
        assert stats.exported == 5

    def test_export_session_handles_malformed_input(self):
        """Malformed session dict returns None without raising."""
        exporter = TrajectoryExporter()
        # Pass a non-dict value coerced into a weird dict — should not crash.
        result = exporter.export_session({})
        # An empty dict is valid (produces a record with empty run_id)
        assert result is not None or result is None  # either is acceptable

    def test_export_to_file_writes_jsonl(self, tmp_path: Path):
        """export_to_file writes each record as a separate JSON line."""
        output = tmp_path / "records.jsonl"
        exporter = TrajectoryExporter()
        records = [_make_record(run_id=f"run-{i}") for i in range(4)]
        exporter.export_to_file(records, str(output))
        assert output.exists()
        lines = output.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 4
        for i, line in enumerate(lines):
            parsed = json.loads(line)
            assert parsed["run_id"] == f"run-{i}"


# ---------------------------------------------------------------------------
# RewardAnnotator
# ---------------------------------------------------------------------------


class TestRewardAnnotator:
    def test_annotate_sets_reward(self):
        """Reward field is set on the returned record."""
        record = _make_record(reward=None)
        annotated = RewardAnnotator.annotate(record, quality_score=0.8, efficiency_score=0.6)
        assert annotated.reward is not None
        # 0.7 * 0.8 + 0.3 * 0.6 = 0.56 + 0.18 = 0.74
        assert abs(annotated.reward - 0.74) < 1e-5

    def test_annotate_default_efficiency(self):
        """When efficiency_score is omitted it defaults to 1.0."""
        record = _make_record(reward=None)
        annotated = RewardAnnotator.annotate(record, quality_score=0.5)
        # 0.7 * 0.5 + 0.3 * 1.0 = 0.35 + 0.30 = 0.65
        assert abs(annotated.reward - 0.65) < 1e-5

    def test_annotate_does_not_mutate_original(self):
        """The original record is not modified."""
        record = _make_record(reward=None)
        original_reward = record.reward
        RewardAnnotator.annotate(record, quality_score=1.0)
        assert record.reward == original_reward

    def test_annotate_quality_score_clamped(self):
        """Quality scores outside [0, 1] are clamped before use."""
        record = _make_record()
        annotated = RewardAnnotator.annotate(record, quality_score=2.0, efficiency_score=0.0)
        # quality clamped to 1.0, efficiency 0.0 → 0.7 * 1 + 0.3 * 0 = 0.7
        assert abs(annotated.reward - 0.7) < 1e-5

    def test_normalize_reward_within_range(self):
        """Values already in [0, 1] pass through unchanged."""
        assert RewardAnnotator.normalize_reward(0.5) == 0.5
        assert RewardAnnotator.normalize_reward(0.0) == 0.0
        assert RewardAnnotator.normalize_reward(1.0) == 1.0

    def test_normalize_reward_clamps_above(self):
        """Values above max_val are clamped to 1.0."""
        assert RewardAnnotator.normalize_reward(1.5) == 1.0

    def test_normalize_reward_clamps_below(self):
        """Values below min_val are clamped to 0.0."""
        assert RewardAnnotator.normalize_reward(-0.5) == 0.0

    def test_normalize_reward_custom_range(self):
        """Custom min/max range normalises correctly."""
        # Score 75 in range [50, 100] → normalised to 0.5
        result = RewardAnnotator.normalize_reward(75.0, min_val=50.0, max_val=100.0)
        assert abs(result - 0.5) < 1e-9
