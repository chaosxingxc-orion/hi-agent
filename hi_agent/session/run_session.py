"""Unified session object for a TRACE run.

RunSession owns ALL state for a single run execution:
- Working memory (L0/L1/L2)
- Event history
- LLM interaction tracking (sent context registry)
- Compact boundary for context deduplication
- Checkpoint/restore capability

Design principles:
- Session is the single source of truth (no scattered state)
- L0 is persisted (JSONL append-only) for resume capability
- Compact boundary prevents resending compressed context
- Every LLM call is tracked for cost and dedup
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from hi_agent.contracts.reasoning import ReasoningTrace


@dataclass
class LLMCallRecord:
    """Record of a single LLM call made during this session."""

    call_id: str
    purpose: str  # "routing", "compression", "skill_extraction", "action"
    stage_id: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    context_hash: str = ""  # hash of context sent, for dedup detection
    timestamp: str = ""


@dataclass
class CompactBoundary:
    """Marks the point up to which context has been compressed.

    All context BEFORE this boundary has been summarized into L1.
    Task View builder should only include content AFTER this boundary
    (plus L1 summaries of what came before).
    """

    stage_id: str
    event_offset: int  # L0 record index up to which was compressed
    timestamp: str = ""
    summary_ref: str = ""  # reference to L1 summary that replaced this content


class RunSession:
    """Unified session for a TRACE run.

    Owns all state, provides context building, supports checkpoint/restore.
    """

    def __init__(
        self,
        run_id: str,
        task_contract: Any = None,  # TaskContract
        *,
        policy_versions: Any | None = None,  # PolicyVersionSet
        storage_dir: str | None = None,  # for L0 persistence
        project_id: str = "",
    ) -> None:
        """Initialize RunSession."""
        self.run_id = run_id
        self.task_contract = task_contract
        self.policy_versions = policy_versions
        self._storage_dir = storage_dir
        self._project_id = project_id

        # Working Memory
        self.l0_records: list[dict] = []  # raw events (also persisted if storage_dir)
        self.l1_summaries: dict[str, dict] = {}  # stage_id -> compressed summary
        self.l2_index: dict[str, Any] = {}  # run navigation index

        # Event history
        self.events: list[dict] = []

        # Stage tracking
        self.current_stage: str = ""
        self.stage_states: dict[str, str] = {}
        self.stage_attempt: dict[str, int] = {}
        # RUNTIME-ONLY: per-run counters, valid for instance lifetime.
        self.action_seq: int = 0
        self.branch_seq: int = 0

        # LLM interaction tracking
        self.llm_calls: list[LLMCallRecord] = []
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cost_usd: float = 0.0

        # Compact boundary (dedup mechanism)
        self._compact_boundaries: list[CompactBoundary] = []

        # Ensure storage dir
        if self._storage_dir:
            os.makedirs(self._storage_dir, exist_ok=True)

    # --- L0 Raw Memory ---
    def append_record(self, event_type: str, payload: dict, stage_id: str | None = None) -> int:
        """Append raw event record. Returns record index.

        If storage_dir set, also appends to JSONL file.
        """
        record = {
            "index": len(self.l0_records),
            "event_type": event_type,
            "payload": payload,
            "stage_id": stage_id or self.current_stage,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.l0_records.append(record)
        if self._storage_dir:
            self._persist_l0_record(record)
        return record["index"]

    def get_records_after_boundary(self) -> list[dict]:
        """Get L0 records AFTER the last compact boundary.

        This is what hasn't been compressed yet.
        """
        if not self._compact_boundaries:
            return list(self.l0_records)
        last_boundary = self._compact_boundaries[-1]
        return [r for r in self.l0_records if r["index"] > last_boundary.event_offset]

    def get_records_for_stage(self, stage_id: str) -> list[dict]:
        """Get all L0 records for a specific stage."""
        return [r for r in self.l0_records if r.get("stage_id") == stage_id]

    # --- L1 Compressed ---
    def set_stage_summary(self, stage_id: str, summary: dict) -> None:
        """Store compressed stage summary (L1)."""
        self.l1_summaries[stage_id] = summary

    def get_stage_summary(self, stage_id: str) -> dict | None:
        """Retrieve compressed stage summary (L1)."""
        return self.l1_summaries.get(stage_id)

    # --- Compact Boundary ---
    def mark_compact_boundary(self, stage_id: str, summary_ref: str = "") -> None:
        """Mark current position as compressed.

        All L0 records up to now have been summarized into L1.
        """
        boundary = CompactBoundary(
            stage_id=stage_id,
            event_offset=len(self.l0_records) - 1,
            timestamp=datetime.now(UTC).isoformat(),
            summary_ref=summary_ref,
        )
        self._compact_boundaries.append(boundary)

    @property
    def last_compact_boundary(self) -> CompactBoundary | None:
        """Return the most recent compact boundary, or None."""
        return self._compact_boundaries[-1] if self._compact_boundaries else None

    @property
    def project_id(self) -> str:
        """Return the project_id this session is scoped to."""
        return self._project_id

    def write_reasoning_trace(self, trace: ReasoningTrace) -> None:
        """Persist a structured reasoning trace via L0 append_record."""
        self.append_record(
            "reasoning_trace",
            {
                "trace_id": trace.trace_id,
                "stage_id": trace.stage_id,
                "steps": [
                    {
                        "step_id": s.step_id,
                        "action": s.action,
                        "thought": s.thought,
                        "timestamp": s.timestamp,
                    }
                    for s in trace.steps
                ],
            },
        )

    # --- LLM Call Tracking ---
    def record_llm_call(self, record: LLMCallRecord) -> None:
        """Record an LLM call for cost tracking and dedup."""
        self.llm_calls.append(record)
        self.total_input_tokens += record.input_tokens
        self.total_output_tokens += record.output_tokens
        self.total_cost_usd += record.cost_usd

    def get_llm_calls_for_stage(self, stage_id: str) -> list[LLMCallRecord]:
        """Return LLM calls associated with *stage_id*."""
        return [c for c in self.llm_calls if c.stage_id == stage_id]

    def get_cost_summary(self) -> dict[str, Any]:
        """Return cost breakdown by stage and purpose."""
        by_stage: dict[str, float] = {}
        by_purpose: dict[str, float] = {}
        for call in self.llm_calls:
            by_stage[call.stage_id] = by_stage.get(call.stage_id, 0) + call.cost_usd
            by_purpose[call.purpose] = by_purpose.get(call.purpose, 0) + call.cost_usd
        return {
            "total_cost_usd": self.total_cost_usd,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_llm_calls": len(self.llm_calls),
            "by_stage": by_stage,
            "by_purpose": by_purpose,
        }

    # --- Event Tracking ---
    def emit_event(self, event_type: str, payload: dict) -> dict:
        """Emit and store an event."""
        event = {
            "event_type": event_type,
            "run_id": self.run_id,
            "payload": payload,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.events.append(event)
        return event

    # --- Checkpoint / Restore ---
    def to_checkpoint(self) -> dict[str, Any]:
        """Serialize full session state for persistence."""
        return {
            "run_id": self.run_id,
            "task_contract": _serialize_contract(self.task_contract),
            "current_stage": self.current_stage,
            "stage_states": dict(self.stage_states),
            "stage_attempt": dict(self.stage_attempt),
            "action_seq": self.action_seq,
            "branch_seq": self.branch_seq,
            "l0_records": list(self.l0_records),
            "l1_summaries": dict(self.l1_summaries),
            "events": list(self.events),
            "llm_calls": [_serialize_llm_call(c) for c in self.llm_calls],
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": self.total_cost_usd,
            "compact_boundaries": [
                {
                    "stage_id": b.stage_id,
                    "event_offset": b.event_offset,
                    "timestamp": b.timestamp,
                    "summary_ref": b.summary_ref,
                }
                for b in self._compact_boundaries
            ],
            "checkpoint_timestamp": datetime.now(UTC).isoformat(),
        }

    @classmethod
    def from_checkpoint(cls, data: dict, task_contract: Any = None) -> RunSession:
        """Restore session from checkpoint data."""
        session = cls(
            run_id=data["run_id"],
            task_contract=task_contract,
        )
        session.current_stage = data.get("current_stage", "")
        session.stage_states = data.get("stage_states", {})
        session.stage_attempt = data.get("stage_attempt", {})
        session.action_seq = data.get("action_seq", 0)
        session.branch_seq = data.get("branch_seq", 0)
        session.l0_records = data.get("l0_records", [])
        session.l1_summaries = data.get("l1_summaries", {})
        session.events = data.get("events", [])
        session.total_input_tokens = data.get("total_input_tokens", 0)
        session.total_output_tokens = data.get("total_output_tokens", 0)
        session.total_cost_usd = data.get("total_cost_usd", 0.0)
        # Restore LLM calls
        for call_data in data.get("llm_calls", []):
            session.llm_calls.append(LLMCallRecord(**call_data))
        # Restore compact boundaries
        for bd in data.get("compact_boundaries", []):
            session._compact_boundaries.append(CompactBoundary(**bd))
        return session

    def save_checkpoint(self, path: str | None = None) -> str:
        """Save checkpoint to JSON file. Returns file path."""
        if path is None:
            if self._storage_dir:
                path = os.path.join(self._storage_dir, f"checkpoint_{self.run_id}.json")
            else:
                path = os.path.join(".checkpoint", f"checkpoint_{self.run_id}.json")
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_checkpoint(), f, indent=2, default=str)
        return path

    @classmethod
    def load_checkpoint(cls, path: str, task_contract: Any = None) -> RunSession:
        """Load session from checkpoint file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_checkpoint(data, task_contract)

    # --- L0 Persistence (JSONL) ---
    def _persist_l0_record(self, record: dict) -> None:
        """Append single L0 record to JSONL file."""
        assert self._storage_dir is not None
        path = os.path.join(self._storage_dir, f"l0_{self.run_id}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def load_l0_from_disk(self) -> int:
        """Load L0 records from JSONL file. Returns count loaded."""
        if not self._storage_dir:
            return 0
        path = os.path.join(self._storage_dir, f"l0_{self.run_id}.jsonl")
        if not os.path.exists(path):
            return 0
        loaded = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.l0_records.append(json.loads(line))
                    loaded += 1
        return loaded

    # --- Context Building (dedup-aware) ---
    def build_context_for_llm(self, purpose: str, budget_tokens: int = 8192) -> dict[str, Any]:
        """Build deduplicated context for an LLM call.

        Uses compact boundary to avoid resending compressed content.
        Returns dict with sections that fit within budget.
        """
        context: dict[str, Any] = {}
        used_tokens = 0

        # 1. Contract summary (always included, ~200 tokens)
        contract_text = f"Task: {getattr(self.task_contract, 'goal', '')}"
        context["contract"] = contract_text
        used_tokens += len(contract_text) // 4

        # 2. Current stage state (~100 tokens)
        context["stage"] = {
            "current": self.current_stage,
            "states": dict(self.stage_states),
        }
        used_tokens += 100

        # 3. L1 summaries for completed stages (compressed, deduped by design)
        summaries = {}
        for stage_id, summary in self.l1_summaries.items():
            summary_text = json.dumps(summary, default=str)
            summary_tokens = len(summary_text) // 4
            if used_tokens + summary_tokens < budget_tokens * 0.6:
                summaries[stage_id] = summary
                used_tokens += summary_tokens
        context["stage_summaries"] = summaries

        # 4. Uncompressed records (AFTER compact boundary only)
        fresh_records = self.get_records_after_boundary()
        records_text = []
        for r in fresh_records:
            r_text = f"[{r['event_type']}] {json.dumps(r['payload'], default=str)}"
            r_tokens = len(r_text) // 4
            if used_tokens + r_tokens < budget_tokens * 0.85:
                records_text.append(r_text)
                used_tokens += r_tokens
        context["fresh_evidence"] = records_text

        # 5. Metadata
        context["budget_used_tokens"] = used_tokens
        context["budget_total_tokens"] = budget_tokens
        context["purpose"] = purpose
        context["compact_boundary"] = (
            {
                "stage_id": self.last_compact_boundary.stage_id,
                "offset": self.last_compact_boundary.event_offset,
            }
            if self.last_compact_boundary
            else None
        )

        return context


def _serialize_contract(contract: Any) -> dict:
    """Serialize TaskContract to dict."""
    if hasattr(contract, "__dict__"):
        return {k: v for k, v in contract.__dict__.items() if not k.startswith("_")}
    return {"raw": str(contract)}


def _serialize_llm_call(call: LLMCallRecord) -> dict:
    """Serialize LLMCallRecord to dict."""
    return {
        "call_id": call.call_id,
        "purpose": call.purpose,
        "stage_id": call.stage_id,
        "model": call.model,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "cache_read_tokens": call.cache_read_tokens,
        "cache_creation_tokens": call.cache_creation_tokens,
        "cost_usd": call.cost_usd,
        "context_hash": call.context_hash,
        "timestamp": call.timestamp,
    }
