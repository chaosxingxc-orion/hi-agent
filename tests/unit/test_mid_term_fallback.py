"""Regression tests for mid_term list_recent fallback path (E-6).

The fallback path (no _manifest.json) previously raised NameError because
it returned ``summaries[:days]`` but the variable is named ``all_summaries``.
"""

import json
import time
from pathlib import Path

from hi_agent.memory.mid_term import MidTermMemoryStore


def _write_summary(storage_dir: Path, date: str, text: str = "summary") -> None:
    data = {
        "date": date,
        "summary": text,
        "run_ids": [],
        "created_at": time.time(),
    }
    (storage_dir / f"{date}.json").write_text(json.dumps(data), encoding="utf-8")


def test_list_recent_fallback_no_manifest(tmp_path: Path) -> None:
    """Fallback path (no manifest) must not raise NameError and must return results."""
    store = MidTermMemoryStore(storage_dir=tmp_path)
    _write_summary(tmp_path, "2026-04-18", "summary A")
    _write_summary(tmp_path, "2026-04-19", "summary B")
    assert not (tmp_path / "_manifest.json").exists()
    result = store.list_recent(days=5)
    assert len(result) == 2
    # newest first
    assert result[0].date == "2026-04-19"


def test_list_recent_fallback_respects_days_limit(tmp_path: Path) -> None:
    """Fallback path must honour the days limit."""
    store = MidTermMemoryStore(storage_dir=tmp_path)
    for i in range(5):
        _write_summary(tmp_path, f"2026-04-{10 + i:02d}")
    result = store.list_recent(days=3)
    assert len(result) == 3
