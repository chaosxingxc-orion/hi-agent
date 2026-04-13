"""
Structured Context Compression for hi-agent.

Provides a structured compression template that preserves critical
information across compression cycles. Instead of naive summarization,
uses a five-field schema (Goal/Progress/Decisions/Files/NextSteps)
to ensure no key context is lost.

Inspired by Hermes Agent's structured summarization approach.

Usage:
    compressor = StructuredCompressor(llm_gateway, config)
    result = await compressor.compress(messages, existing_summary=None)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from hi_agent.llm import AsyncLLMGateway, LLMRequest, LLMResponse

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CompressionField
# ---------------------------------------------------------------------------


class CompressionField(StrEnum):
    """Field identifiers for the structured summary schema."""

    GOAL = "goal"                    # User's original task goal (immutable across compression cycles)
    PROGRESS = "progress"            # Work completed so far
    DECISIONS = "decisions"          # Key decisions and choices made
    MODIFIED_FILES = "modified_files"  # List of files that were changed
    NEXT_STEPS = "next_steps"        # Remaining work to be done


# ---------------------------------------------------------------------------
# StructuredSummary
# ---------------------------------------------------------------------------


@dataclass
class StructuredSummary:
    """A structured summary produced by one compression cycle.

    Holds the five canonical fields (Goal / Progress / Decisions /
    ModifiedFiles / NextSteps) together with metadata about *when* and
    *how many messages* were compressed.
    """

    goal: str
    progress: str
    decisions: str
    modified_files: list[str]
    next_steps: str
    compressed_at: str            # ISO 8601 timestamp
    source_message_count: int     # Number of messages that were compressed

    def to_context_block(self) -> str:
        """Return a formatted context block suitable for injection into a TaskView.

        Example output::

            [CONTEXT COMPACTION - 2026-04-10T12:00:00+00:00]
            目标: Refactor the LLM gateway
            进度: Completed protocol definition and HTTP gateway
            关键决策: Chose httpx for async transport; pinned to Python 3.12+
            已修改文件:
              hi_agent/llm/protocol.py
              hi_agent/llm/http_gateway.py
            下一步: Wire up TierRouter to HttpGateway
            [END COMPACTION - 压缩自 42 条消息]
        """
        files_block: str
        if self.modified_files:
            files_block = "\n".join(f"  {f}" for f in self.modified_files)
        else:
            files_block = "  (无)"

        return (
            f"[CONTEXT COMPACTION - {self.compressed_at}]\n"
            f"目标: {self.goal}\n"
            f"进度: {self.progress}\n"
            f"关键决策: {self.decisions}\n"
            f"已修改文件:\n{files_block}\n"
            f"下一步: {self.next_steps}\n"
            f"[END COMPACTION - 压缩自 {self.source_message_count} 条消息]"
        )

    def merge(self, newer: "StructuredSummary") -> "StructuredSummary":
        """Produce an incremental merged summary from *self* (older) and *newer*.

        Merge rules:
        - **goal**: keep the older one — the original task goal does not change.
        - **progress**: concatenate ("之前: {old}\n新增: {newer}").
        - **decisions**: append newer decisions to older ones.
        - **modified_files**: union, deduplication preserved.
        - **next_steps**: use the newer value — latest remaining work wins.
        - **compressed_at**: use the newer timestamp.
        - **source_message_count**: sum both counts.
        """
        merged_files: list[str] = list(self.modified_files)
        for f in newer.modified_files:
            if f not in merged_files:
                merged_files.append(f)

        merged_progress = f"之前: {self.progress}\n新增: {newer.progress}"
        merged_decisions = (
            f"{self.decisions}\n{newer.decisions}" if newer.decisions else self.decisions
        )

        return StructuredSummary(
            goal=self.goal,  # original goal is immutable
            progress=merged_progress,
            decisions=merged_decisions,
            modified_files=merged_files,
            next_steps=newer.next_steps,
            compressed_at=newer.compressed_at,
            source_message_count=self.source_message_count + newer.source_message_count,
        )

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Convert to a JSON-compatible dict."""
        return {
            CompressionField.GOAL: self.goal,
            CompressionField.PROGRESS: self.progress,
            CompressionField.DECISIONS: self.decisions,
            CompressionField.MODIFIED_FILES: list(self.modified_files),
            CompressionField.NEXT_STEPS: self.next_steps,
            "compressed_at": self.compressed_at,
            "source_message_count": self.source_message_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StructuredSummary":
        """Reconstruct a StructuredSummary from a dict (e.g., loaded from JSON)."""
        return cls(
            goal=d.get(CompressionField.GOAL, ""),
            progress=d.get(CompressionField.PROGRESS, ""),
            decisions=d.get(CompressionField.DECISIONS, ""),
            modified_files=list(d.get(CompressionField.MODIFIED_FILES, [])),
            next_steps=d.get(CompressionField.NEXT_STEPS, ""),
            compressed_at=d.get("compressed_at", ""),
            source_message_count=int(d.get("source_message_count", 0)),
        )


# ---------------------------------------------------------------------------
# CompressionSection
# ---------------------------------------------------------------------------


@dataclass
class CompressionSection:
    """A partitioned view of a message list.

    head_messages : protected prefix messages (system prompt + early context)
    middle_messages: candidates for LLM summarization
    tail_messages  : protected suffix messages (most recent exchanges)
    """

    head_messages: list[dict]
    middle_messages: list[dict]
    tail_messages: list[dict]


# ---------------------------------------------------------------------------
# MessagePartitioner
# ---------------------------------------------------------------------------


class MessagePartitioner:
    """Partitions a message list into head / middle / tail sections.

    Args:
        head_count: Number of messages to protect at the start (default 3).
        tail_token_budget: Approximate character budget for the tail section.
            Uses 1 char ≈ 1 token as a conservative estimate (default 8000).
    """

    def __init__(
        self,
        head_count: int = 3,
        tail_token_budget: int = 8000,
    ) -> None:
        self._head_count = head_count
        self._tail_token_budget = tail_token_budget

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def partition(self, messages: list[dict]) -> CompressionSection:
        """Partition *messages* into head / middle / tail.

        The head always contains the first ``head_count`` messages.
        The tail is built greedily from the end of the list until the
        accumulated character count exceeds ``tail_token_budget``.
        Everything between head and tail is *middle*.

        Edge cases:
        - If the total message count ≤ head_count, all messages go to head.
        - If head and tail overlap, tail wins (head messages are still in head;
          overlapping messages are NOT placed in middle).
        """
        total = len(messages)

        if total <= self._head_count:
            return CompressionSection(
                head_messages=list(messages),
                middle_messages=[],
                tail_messages=[],
            )

        head = messages[: self._head_count]
        remaining = messages[self._head_count :]

        # Build tail greedily from the right
        tail: list[dict] = []
        chars_accumulated = 0
        for msg in reversed(remaining):
            msg_chars = self.estimate_chars(msg)
            if chars_accumulated + msg_chars > self._tail_token_budget:
                break
            tail.insert(0, msg)
            chars_accumulated += msg_chars

        # Middle = everything in remaining that is NOT in tail
        tail_start_index = len(remaining) - len(tail)
        middle = remaining[:tail_start_index]

        return CompressionSection(
            head_messages=head,
            middle_messages=middle,
            tail_messages=tail,
        )

    def estimate_chars(self, msg: dict) -> int:
        """Estimate the character count of a single message dict.

        Walks common content shapes:
        - ``{"content": "string"}``
        - ``{"content": [{"text": "..."}]}`` (multimodal blocks)
        """
        content = msg.get("content", "")
        if isinstance(content, str):
            return len(content)
        if isinstance(content, list):
            total = 0
            for block in content:
                if isinstance(block, dict):
                    total += len(block.get("text", ""))
                elif isinstance(block, str):
                    total += len(block)
            return total
        return len(str(content))


# ---------------------------------------------------------------------------
# StructuredCompressorConfig
# ---------------------------------------------------------------------------


@dataclass
class StructuredCompressorConfig:
    """Configuration knobs for StructuredCompressor."""

    head_count: int = 3
    tail_token_budget: int = 8000
    max_middle_chars_per_compress: int = 16000
    model_tier: str = "light"   # use a lightweight model for compression


# ---------------------------------------------------------------------------
# StructuredCompressor
# ---------------------------------------------------------------------------

_MAX_MSG_CONTENT_CHARS = 2000  # Per-message content truncation in prompts


class StructuredCompressor:
    """LLM-powered structured context compressor.

    Uses a five-field JSON schema to summarize the *middle* portion of a
    conversation while keeping the *head* and *tail* intact.  If an
    ``existing_summary`` is provided the new summary is merged
    incrementally (goal is preserved; progress is appended; files are
    deduped; next_steps are replaced with the freshest value).

    Args:
        llm: An ``AsyncLLMGateway`` instance used for compression calls.
        config: A ``StructuredCompressorConfig`` instance (or default).
    """

    def __init__(
        self,
        llm: AsyncLLMGateway,
        config: StructuredCompressorConfig | None = None,
    ) -> None:
        self._llm = llm
        self._config = config or StructuredCompressorConfig()
        self._partitioner = MessagePartitioner(
            head_count=self._config.head_count,
            tail_token_budget=self._config.tail_token_budget,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def compress(
        self,
        messages: list[dict],
        existing_summary: StructuredSummary | None = None,
    ) -> tuple[list[dict], StructuredSummary]:
        """Compress *messages* using a structured LLM summary.

        Returns a tuple of:
        - ``new_messages``: ``[summary_injection_message] + head + tail``
          (the *middle* is replaced by the summary context block).
        - ``new_summary``: the ``StructuredSummary`` produced (or merged).
        """
        section = self._partitioner.partition(messages)

        if not section.middle_messages:
            # Nothing to compress — return messages unchanged with a minimal summary
            fallback = self._minimal_summary(messages)
            if existing_summary is not None:
                fallback = existing_summary.merge(fallback)
            return list(messages), fallback

        new_summary = await self._call_llm_for_summary(
            section.middle_messages, existing_summary
        )

        if existing_summary is not None:
            new_summary = existing_summary.merge(new_summary)

        injection_message: dict = {
            "role": "system",
            "content": new_summary.to_context_block(),
        }

        new_messages = [injection_message] + section.head_messages + section.tail_messages
        return new_messages, new_summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_llm_for_summary(
        self,
        middle_messages: list[dict],
        existing_summary: StructuredSummary | None,
    ) -> StructuredSummary:
        """Call the LLM and parse the structured summary response."""
        prompt = self._build_compression_prompt(middle_messages, existing_summary)
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            model=self._config.model_tier,
            temperature=0.2,  # low temp for deterministic structured output
            max_tokens=1024,
        )
        try:
            response: LLMResponse = await self._llm.complete(request)
            return self._parse_llm_response(response.content, middle_messages)
        except Exception as exc:
            logger.warning(
                "StructuredCompressor: LLM call failed (%s); using fallback.", exc
            )
            return self._minimal_summary(middle_messages)

    def _build_compression_prompt(
        self,
        middle_messages: list[dict],
        existing_summary: StructuredSummary | None,
    ) -> str:
        """Build the compression prompt sent to the LLM.

        If *existing_summary* is given, asks the model to perform an
        *incremental update* rather than a full summarization.
        """
        serialized = self._serialize_messages_for_prompt(middle_messages)

        if existing_summary is not None:
            existing_block = json.dumps(existing_summary.to_dict(), ensure_ascii=False, indent=2)
            return (
                "你是一个上下文压缩助手。以下是已有的结构化摘要，以及新的对话消息。\n"
                "请根据新消息对摘要进行增量更新，严格按照以下 JSON 格式返回（不要包含额外文字）：\n"
                "{\n"
                '  "goal": "用户的原始任务目标（保持不变）",\n'
                '  "progress": "新增完成的具体工作（只写新增部分）",\n'
                '  "decisions": "新增的关键决策和原因（只写新增部分）",\n'
                '  "modified_files": ["新增的文件路径"],\n'
                '  "next_steps": "尚未完成、需要继续的工作"\n'
                "}\n\n"
                f"已有摘要：\n{existing_block}\n\n"
                f"新对话消息：\n{serialized}"
            )

        return (
            "你是一个上下文压缩助手。请分析以下对话消息，提取结构化摘要。\n"
            "严格按照以下 JSON 格式返回（不要包含额外文字）：\n"
            "{\n"
            '  "goal": "用户的原始任务目标",\n'
            '  "progress": "已完成的具体工作",\n'
            '  "decisions": "做出的关键决策和原因",\n'
            '  "modified_files": ["文件路径1", "文件路径2"],\n'
            '  "next_steps": "尚未完成、需要继续的工作"\n'
            "}\n\n"
            f"对话消息：\n{serialized}"
        )

    def _parse_llm_response(
        self,
        response_content: str,
        fallback_messages: list[dict],
    ) -> StructuredSummary:
        """Parse LLM response as JSON.  Falls back to a minimal summary on error."""
        # Strip markdown code fences if present
        text = response_content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # Drop first and last fence lines
            inner = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.startswith("```") and in_block:
                    break
                if in_block:
                    inner.append(line)
            text = "\n".join(inner)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find the first JSON object in the text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    data = json.loads(text[start:end])
                except json.JSONDecodeError:
                    logger.warning(
                        "StructuredCompressor: failed to parse LLM JSON; using fallback."
                    )
                    return self._minimal_summary(fallback_messages)
            else:
                logger.warning(
                    "StructuredCompressor: no JSON object found in LLM response; using fallback."
                )
                return self._minimal_summary(fallback_messages)

        now = datetime.now(UTC).isoformat()
        modified_files = data.get(CompressionField.MODIFIED_FILES, [])
        if not isinstance(modified_files, list):
            modified_files = []

        return StructuredSummary(
            goal=str(data.get(CompressionField.GOAL, "")),
            progress=str(data.get(CompressionField.PROGRESS, "")),
            decisions=str(data.get(CompressionField.DECISIONS, "")),
            modified_files=[str(f) for f in modified_files],
            next_steps=str(data.get(CompressionField.NEXT_STEPS, "")),
            compressed_at=now,
            source_message_count=len(fallback_messages),
        )

    def _serialize_messages_for_prompt(self, messages: list[dict]) -> str:
        """Serialize messages to a concise text form for the compression prompt.

        Each message is rendered as::

            [role]: {content}

        Content that exceeds ``_MAX_MSG_CONTENT_CHARS`` is truncated with an
        ellipsis so that the prompt stays within a reasonable size.
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Flatten multimodal content blocks to text
                text_parts: list[str] = []
                for block in content:
                    if isinstance(block, dict):
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = " ".join(text_parts)
            content_str = str(content)
            if len(content_str) > _MAX_MSG_CONTENT_CHARS:
                content_str = content_str[:_MAX_MSG_CONTENT_CHARS] + "...[truncated]"
            parts.append(f"[{role}]: {content_str}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Fallback helpers
    # ------------------------------------------------------------------

    def _minimal_summary(self, messages: list[dict]) -> StructuredSummary:
        """Produce a best-effort summary without LLM involvement.

        Extracts the first user message as the *goal* and concatenates all
        assistant messages as a rough *progress* indicator.
        """
        logger.warning(
            "structured_compression: LLM unavailable, using minimal fallback summary for section %r",
            getattr(self, "section_id", "unknown"),
        )
        goal = ""
        progress_parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                )
            content_str = str(content)[:500]
            if role == "user" and not goal:
                goal = content_str
            elif role == "assistant":
                progress_parts.append(content_str)

        return StructuredSummary(
            goal=goal or "(goal_unknown)",
            progress="; ".join(progress_parts[:3]) or "(no_progress_recorded)",
            decisions="(no_decisions_recorded)",
            modified_files=[],
            next_steps="(pending_confirmation)",
            compressed_at=datetime.now(UTC).isoformat(),
            source_message_count=len(messages),
        )
