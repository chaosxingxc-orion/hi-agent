"""RL Trajectory Exporter for hi-agent.

Exports agent conversation trajectories to JSONL format for
reinforcement learning training. Each trajectory captures a complete
run with messages, tool calls, reasoning blocks, and optional rewards.

Output format is compatible with OpenAI SFT format and common RL frameworks.

Usage:
    exporter = TrajectoryExporter()
    exporter.export_session(session_data, output_path)
    exporter.export_batch(sessions_dir, output_path, min_quality=0.7)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------


@dataclass
class TrajectoryMessage:
    """A single message in a trajectory conversation.

    Attributes:
        role: One of "user", "assistant", "tool", or "system".
        content: Text content of the message.
        reasoning: Optional thinking/reasoning block from the model.
        tool_calls: Optional list of tool calls made in this message.
            Each entry is a dict with keys: name, id, input.
        tool_call_id: For tool-role messages, the ID of the call being responded to.
        timestamp: ISO 8601 timestamp string, if available.
    """

    role: str
    content: str
    reasoning: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    timestamp: str | None = None

    def to_dict(self) -> dict:
        """Serialize to dict, omitting fields that are None."""
        result: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.reasoning is not None:
            result["reasoning"] = self.reasoning
        if self.tool_calls is not None:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id
        if self.timestamp is not None:
            result["timestamp"] = self.timestamp
        return result


@dataclass
class TrajectoryRecord:
    """A complete RL training trajectory for one agent run.

    Attributes:
        run_id: Unique identifier for the run.
        task_id: Optional task contract identifier.
        messages: Ordered list of conversation messages.
        reward: Scalar reward injected by a RewardAnnotator (if any).
        quality_score: Quality score from evaluation pipeline (0.0–1.0).
        skill_id: Identifier of the primary skill used (if any).
        total_turns: Number of user/assistant turn pairs.
        total_tool_calls: Total number of tool calls across all messages.
        created_at: ISO 8601 timestamp when this record was created.
        metadata: Arbitrary extra metadata dict.
    """

    run_id: str
    task_id: str | None
    messages: list[TrajectoryMessage]
    reward: float | None = None
    quality_score: float | None = None
    skill_id: str | None = None
    total_turns: int = 0
    total_tool_calls: int = 0
    created_at: str = ""
    metadata: dict = field(default_factory=dict)

    def to_jsonl_line(self) -> str:
        """Serialize to a single JSON line (no trailing newline).

        Uses ensure_ascii=False to preserve Unicode characters.
        """
        data = {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "messages": [m.to_dict() for m in self.messages],
            "reward": self.reward,
            "quality_score": self.quality_score,
            "skill_id": self.skill_id,
            "total_turns": self.total_turns,
            "total_tool_calls": self.total_tool_calls,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> TrajectoryRecord:
        """Reconstruct a TrajectoryRecord from a plain dict (e.g. loaded from JSONL)."""
        raw_messages = d.get("messages", [])
        messages: list[TrajectoryMessage] = []
        for m in raw_messages:
            if isinstance(m, dict):
                messages.append(
                    TrajectoryMessage(
                        role=m.get("role", "user"),
                        content=m.get("content", ""),
                        reasoning=m.get("reasoning"),
                        tool_calls=m.get("tool_calls"),
                        tool_call_id=m.get("tool_call_id"),
                        timestamp=m.get("timestamp"),
                    )
                )
        return cls(
            run_id=d.get("run_id", ""),
            task_id=d.get("task_id"),
            messages=messages,
            reward=d.get("reward"),
            quality_score=d.get("quality_score"),
            skill_id=d.get("skill_id"),
            total_turns=d.get("total_turns", 0),
            total_tool_calls=d.get("total_tool_calls", 0),
            created_at=d.get("created_at", ""),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


@dataclass
class TrajectoryFilter:
    """Configurable filter that decides whether a TrajectoryRecord should be kept.

    Attributes:
        min_quality: Minimum quality_score required (inclusive).
        min_turns: Minimum total_turns required (inclusive).
        max_turns: Maximum total_turns allowed (inclusive).
        require_reward: When True, records without a reward are rejected.
        allowed_statuses: Run statuses that are accepted. Checked against
            record.metadata["status"] when present.
    """

    min_quality: float = 0.0
    min_turns: int = 1
    max_turns: int = 1000
    require_reward: bool = False
    allowed_statuses: list[str] = field(default_factory=lambda: ["completed"])

    def accept(self, record: TrajectoryRecord) -> bool:
        """Return True if the record satisfies all filter criteria."""
        # Quality gate
        if record.quality_score is not None and record.quality_score < self.min_quality:
            return False

        # Turn count gates
        if record.total_turns < self.min_turns:
            return False
        if record.total_turns > self.max_turns:
            return False

        # Reward gate
        if self.require_reward and record.reward is None:
            return False

        # Status gate (only enforced when metadata carries a "status" key)
        status = record.metadata.get("status")
        if status is not None and status not in self.allowed_statuses:
            return False

        return True


# ---------------------------------------------------------------------------
# Session message parsing
# ---------------------------------------------------------------------------


class SessionMessageParser:
    """Stateless helpers for extracting TrajectoryMessages from session dicts."""

    @staticmethod
    def parse_messages(session_dict: dict) -> list[TrajectoryMessage]:
        """Extract a list of TrajectoryMessages from a session dictionary.

        Looks for messages under the keys "messages" or "history".
        Handles dicts with "role"/"content" and optional "tool_calls",
        "reasoning", and "thinking" keys.

        Args:
            session_dict: Raw session data dict (e.g. from a checkpoint JSON).

        Returns:
            Ordered list of TrajectoryMessage objects.
        """
        raw: list[Any] = session_dict.get("messages") or session_dict.get("history", [])
        result: list[TrajectoryMessage] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            role = item.get("role", "user")
            content = item.get("content", "")
            # content might be a list (e.g. Anthropic multi-part format)
            if isinstance(content, list):
                content = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            reasoning = SessionMessageParser.extract_reasoning(item)
            tool_calls = SessionMessageParser.extract_tool_calls(item)
            result.append(
                TrajectoryMessage(
                    role=str(role),
                    content=str(content),
                    reasoning=reasoning,
                    tool_calls=tool_calls,
                    tool_call_id=item.get("tool_call_id"),
                    timestamp=item.get("timestamp"),
                )
            )
        return result

    @staticmethod
    def extract_tool_calls(msg: dict) -> list[dict] | None:
        """Extract tool_calls list from a raw message dict.

        Accepts both the standard "tool_calls" key and the Anthropic
        content-block format where role=="assistant" and content is a list
        containing blocks with type=="tool_use".

        Returns None when no tool calls are found.
        """
        # Standard key
        raw = msg.get("tool_calls")
        if isinstance(raw, list) and raw:
            return raw

        # Anthropic content-block format
        content = msg.get("content")
        if isinstance(content, list):
            calls = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append(
                        {
                            "name": block.get("name", ""),
                            "id": block.get("id", ""),
                            "input": block.get("input", {}),
                        }
                    )
            if calls:
                return calls

        return None

    @staticmethod
    def extract_reasoning(msg: dict) -> str | None:
        """Extract reasoning/thinking text from a raw message dict.

        Checks the "reasoning" key first, then "thinking".
        Also handles Anthropic content-block format where a block has
        type=="thinking".

        Returns None when no reasoning block is found.
        """
        # Direct keys
        for key in ("reasoning", "thinking"):
            val = msg.get(key)
            if isinstance(val, str) and val.strip():
                return val

        # Anthropic content-block format
        content = msg.get("content")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    text = block.get("thinking", "") or block.get("text", "")
                    if text:
                        parts.append(text)
            if parts:
                return "\n".join(parts)

        return None


# ---------------------------------------------------------------------------
# Export statistics
# ---------------------------------------------------------------------------


@dataclass
class ExportStats:
    """Summary statistics returned after a batch export.

    Attributes:
        total_sessions: Number of session dicts submitted for export.
        exported: Number that passed the filter and were written.
        filtered_out: Number rejected by the filter.
        errors: Number that raised exceptions during processing.
        output_path: Filesystem path of the output JSONL file.
    """

    total_sessions: int = 0
    exported: int = 0
    filtered_out: int = 0
    errors: int = 0
    output_path: str = ""


# ---------------------------------------------------------------------------
# Main exporter
# ---------------------------------------------------------------------------


class TrajectoryExporter:
    """Exports agent run sessions to JSONL format for RL training.

    Each exported record corresponds to one complete run and captures the
    full conversation (messages, tool calls, reasoning blocks) plus optional
    quality / reward signals.

    Args:
        filter: Optional filter applied before writing. Records that do not
            pass the filter are counted in ExportStats.filtered_out and
            export_session returns None.
    """

    def __init__(self, filter: TrajectoryFilter | None = None) -> None:
        self._filter = filter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_session(
        self,
        session_dict: dict,
        output_path: str | None = None,
    ) -> TrajectoryRecord | None:
        """Export a single session to an optional JSONL file.

        Args:
            session_dict: Raw session data (checkpoint dict or similar).
            output_path: When provided, the record is *appended* to this file.

        Returns:
            The constructed TrajectoryRecord, or None if filtered out or if an
            error occurred during parsing.
        """
        try:
            record = self._build_record(session_dict)
        except Exception as exc:
            _logger.warning("trajectory_exporter.parse_error error=%s", exc)
            return None

        if self._filter is not None and not self._filter.accept(record):
            return None

        if output_path is not None:
            self._append_record(record, output_path)

        return record

    def export_batch(
        self,
        sessions: list[dict],
        output_path: str,
    ) -> ExportStats:
        """Export a list of session dicts to a single JSONL file.

        Args:
            sessions: List of raw session data dicts.
            output_path: Destination JSONL file (will be created/overwritten).

        Returns:
            ExportStats summarising the outcome.
        """
        stats = ExportStats(total_sessions=len(sessions), output_path=output_path)
        records: list[TrajectoryRecord] = []

        for session_dict in sessions:
            try:
                record = self._build_record(session_dict)
            except Exception as exc:
                _logger.warning("trajectory_exporter.batch_parse_error error=%s", exc)
                stats.errors += 1
                continue

            if self._filter is not None and not self._filter.accept(record):
                stats.filtered_out += 1
                continue

            records.append(record)
            stats.exported += 1

        if records:
            self.export_to_file(records, output_path)

        return stats

    def export_to_file(
        self,
        records: list[TrajectoryRecord],
        output_path: str,
    ) -> None:
        """Write a list of TrajectoryRecords to a JSONL file (one record per line).

        The file is created (or overwritten) at output_path. Parent directories
        are created automatically.

        Args:
            records: Records to write.
            output_path: Destination file path.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(record.to_jsonl_line())
                fh.write("\n")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_record(self, session_dict: dict) -> TrajectoryRecord:
        """Construct a TrajectoryRecord from a raw session dict.

        Handles checkpoint dicts (with "run_id", "l0_records", …) as well as
        simpler dicts that contain "messages" or "history" directly.

        Args:
            session_dict: Raw session data.

        Returns:
            A populated TrajectoryRecord.
        """
        run_id: str = session_dict.get("run_id", "")
        task_id: str | None = session_dict.get("task_id")

        # Try to derive task_id from task_contract if not top-level
        if task_id is None:
            contract = session_dict.get("task_contract")
            if isinstance(contract, dict):
                task_id = contract.get("task_id") or contract.get("id")

        # Parse messages
        messages = SessionMessageParser.parse_messages(session_dict)

        # If no top-level messages, try synthesising from l0_records
        if not messages:
            messages = self._messages_from_l0(session_dict.get("l0_records", []))

        # Quality / skill metadata
        quality_score: float | None = session_dict.get("quality_score")
        skill_id: str | None = session_dict.get("skill_id")

        # Derive counters
        total_turns = sum(
            1 for m in messages if m.role in ("user", "assistant")
        ) // 2
        total_tool_calls = sum(
            len(m.tool_calls) for m in messages if m.tool_calls
        )

        # Timestamp
        created_at = session_dict.get(
            "created_at",
            session_dict.get("checkpoint_timestamp", datetime.now(UTC).isoformat()),
        )

        # Extra metadata (status, cost, etc.)
        metadata: dict = {}
        for key in ("status", "total_cost_usd", "total_input_tokens", "total_output_tokens"):
            val = session_dict.get(key)
            if val is not None:
                metadata[key] = val

        return TrajectoryRecord(
            run_id=run_id,
            task_id=task_id,
            messages=messages,
            quality_score=quality_score,
            skill_id=skill_id,
            total_turns=total_turns,
            total_tool_calls=total_tool_calls,
            created_at=str(created_at),
            metadata=metadata,
        )

    @staticmethod
    def _messages_from_l0(l0_records: list[dict]) -> list[TrajectoryMessage]:
        """Best-effort extraction of messages from L0 raw event records.

        Looks for events of type "llm_input", "llm_output", "action", or
        "action_result" and converts them to TrajectoryMessages.

        Args:
            l0_records: Raw L0 records from a RunSession checkpoint.

        Returns:
            List of synthesised TrajectoryMessages (may be empty).
        """
        messages: list[TrajectoryMessage] = []
        for record in l0_records:
            if not isinstance(record, dict):
                continue
            event_type = record.get("event_type", "")
            payload = record.get("payload", {})
            timestamp = record.get("timestamp")

            if event_type in ("llm_input", "user_message"):
                content = payload.get("content") or payload.get("text", "")
                messages.append(
                    TrajectoryMessage(
                        role="user",
                        content=str(content),
                        timestamp=timestamp,
                    )
                )
            elif event_type in ("llm_output", "assistant_message"):
                content = payload.get("content") or payload.get("text", "")
                reasoning = payload.get("reasoning") or payload.get("thinking")
                tool_calls = payload.get("tool_calls")
                messages.append(
                    TrajectoryMessage(
                        role="assistant",
                        content=str(content),
                        reasoning=reasoning if isinstance(reasoning, str) else None,
                        tool_calls=tool_calls if isinstance(tool_calls, list) else None,
                        timestamp=timestamp,
                    )
                )
            elif event_type == "action":
                tool_name = payload.get("tool") or payload.get("action_type", "unknown")
                call_id = payload.get("action_id") or payload.get("id", "")
                inputs = payload.get("inputs") or payload.get("params", {})
                messages.append(
                    TrajectoryMessage(
                        role="assistant",
                        content="",
                        tool_calls=[{"name": tool_name, "id": call_id, "input": inputs}],
                        timestamp=timestamp,
                    )
                )
            elif event_type == "action_result":
                result_content = payload.get("result") or payload.get("output", "")
                call_id = payload.get("action_id") or payload.get("id", "")
                messages.append(
                    TrajectoryMessage(
                        role="tool",
                        content=str(result_content),
                        tool_call_id=str(call_id) if call_id else None,
                        timestamp=timestamp,
                    )
                )

        return messages

    def _append_record(self, record: TrajectoryRecord, output_path: str) -> None:
        """Append a single record to a JSONL file (creates file if absent)."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(record.to_jsonl_line())
            fh.write("\n")


# ---------------------------------------------------------------------------
# Reward annotation
# ---------------------------------------------------------------------------


class RewardAnnotator:
    """Injects reward signals into TrajectoryRecords.

    Rewards are derived from quality and efficiency scores and normalised to
    the [0, 1] range.  The original record is never mutated; a new record is
    returned instead.
    """

    _QUALITY_WEIGHT = 0.7
    _EFFICIENCY_WEIGHT = 0.3

    @staticmethod
    def annotate(
        record: TrajectoryRecord,
        quality_score: float,
        efficiency_score: float = 1.0,
    ) -> TrajectoryRecord:
        """Compute a reward from quality + efficiency and return a new record.

        The reward is a weighted average:
            reward = 0.7 * quality_score + 0.3 * efficiency_score

        Both inputs are clamped to [0, 1] before the computation.

        Args:
            record: Source record (not mutated).
            quality_score: Quality score in [0, 1].
            efficiency_score: Efficiency score in [0, 1]. Defaults to 1.0.

        Returns:
            A new TrajectoryRecord with the reward and quality_score fields set.
        """
        q = RewardAnnotator.normalize_reward(quality_score)
        e = RewardAnnotator.normalize_reward(efficiency_score)
        reward = RewardAnnotator._QUALITY_WEIGHT * q + RewardAnnotator._EFFICIENCY_WEIGHT * e

        return TrajectoryRecord(
            run_id=record.run_id,
            task_id=record.task_id,
            messages=list(record.messages),
            reward=round(reward, 6),
            quality_score=q,
            skill_id=record.skill_id,
            total_turns=record.total_turns,
            total_tool_calls=record.total_tool_calls,
            created_at=record.created_at,
            metadata=dict(record.metadata),
        )

    @staticmethod
    def normalize_reward(
        raw_score: float,
        min_val: float = 0.0,
        max_val: float = 1.0,
    ) -> float:
        """Clamp and normalise raw_score to [0, 1].

        Args:
            raw_score: Input score (may be outside [0, 1]).
            min_val: Lower bound of the input range. Defaults to 0.0.
            max_val: Upper bound of the input range. Defaults to 1.0.

        Returns:
            Score clamped to [0.0, 1.0].
        """
        if max_val <= min_val:
            return 0.0
        normalised = (raw_score - min_val) / (max_val - min_val)
        return max(0.0, min(1.0, normalised))
