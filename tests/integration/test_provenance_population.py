"""P-1 acceptance tests: built-in capability write paths populate Provenance.

Covers:
- web_fetch_handler returns provenance.url matching the fetched URL.
- file_read_handler returns provenance.url as a file:// URI.
- build_provenance_from_capability_result converts a capability result dict
  into a Provenance instance; returns None when no source key is present.
- make_capability_record returns a RawEventRecord whose provenance.url is
  non-empty for capabilities with a real external source.
- RawMemoryStore JSONL persistence preserves the provenance block.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

from hi_agent.capability.tools.builtin import file_read_handler, web_fetch_handler
from hi_agent.contracts.provenance import Provenance
from hi_agent.memory.l0_raw import (
    RawEventRecord,
    RawMemoryStore,
    build_provenance_from_capability_result,
    make_capability_record,
)


class _FakeResponse:
    """Minimal urllib response stand-in for web_fetch_handler unit tests."""

    def __init__(self, body: bytes, status: int = 200, url: str = "") -> None:
        self._body = body
        self.status = status
        self.url = url

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_web_fetch_populates_provenance_url() -> None:
    """web_fetch_handler result carries provenance.url matching the fetched URL.

    External HTTP is mocked at the urllib layer — the unit under test is the
    handler's provenance-construction logic, not network I/O.
    """
    target_url = "https://example.com/article"

    class _FakeOpener:
        def open(self, req: object, timeout: float) -> _FakeResponse:
            return _FakeResponse(b"<html>hello</html>", status=200, url=target_url)

    with patch("urllib.request.build_opener", return_value=_FakeOpener()):
        result = web_fetch_handler({"url": target_url})

    assert result["success"] is True
    assert "provenance" in result
    prov = result["provenance"]
    assert prov["url"] == target_url
    assert prov["source_type"] == "web"
    assert prov["retrieved_at"]  # non-empty ISO timestamp


def test_file_read_populates_provenance_url(tmp_path: Path) -> None:
    """file_read_handler result carries provenance.url as a file:// URI."""
    target = tmp_path / "sample.txt"
    target.write_text("payload", encoding="utf-8")

    result = file_read_handler({"path": "sample.txt"}, workspace_root=tmp_path)

    assert result["success"] is True, result.get("error")
    assert "provenance" in result
    prov = result["provenance"]
    assert prov["url"].startswith("file:")
    assert prov["source_type"] == "file"
    assert prov["title"] == "sample.txt"
    assert prov["retrieved_at"]


def test_build_provenance_from_capability_result_returns_none_when_absent() -> None:
    """When capability result has no provenance key, helper returns None.

    This encodes the deliberate-None classification for side-effect-only
    capabilities (file_write, shell_exec) and LLM-only synthesis.
    """
    assert build_provenance_from_capability_result(None) is None
    assert build_provenance_from_capability_result({"success": True}) is None
    # Empty url is treated as no-source.
    assert build_provenance_from_capability_result({"provenance": {"url": ""}}) is None


def test_build_provenance_from_capability_result_round_trips_fields() -> None:
    """Provenance fields are copied through verbatim."""
    result = {
        "success": True,
        "provenance": {
            "url": "https://example.com/x",
            "title": "X",
            "source_type": "web",
            "retrieved_at": "2026-04-22T00:00:00+00:00",
        },
    }
    prov = build_provenance_from_capability_result(result)
    assert isinstance(prov, Provenance)
    assert prov.url == "https://example.com/x"
    assert prov.title == "X"
    assert prov.source_type == "web"
    assert prov.retrieved_at == "2026-04-22T00:00:00+00:00"


def test_make_capability_record_web_fetch_has_url() -> None:
    """End-to-end: web_fetch result -> RawEventRecord with non-None provenance.url."""
    target = "https://example.com/report"

    class _FakeOpener:
        def open(self, req: object, timeout: float) -> _FakeResponse:
            return _FakeResponse(b"ok", status=200, url=target)

    with patch("urllib.request.build_opener", return_value=_FakeOpener()):
        cap_result = web_fetch_handler({"url": target})

    record = make_capability_record(
        event_type="ActionExecuted",
        payload={"action_kind": "web_fetch"},
        capability_result=cap_result,
    )
    assert isinstance(record, RawEventRecord)
    assert record.provenance is not None
    assert record.provenance.url == target


def test_make_capability_record_file_read_has_url(tmp_path: Path) -> None:
    """file_read result -> RawEventRecord with file:// provenance.url."""
    target = tmp_path / "doc.md"
    target.write_text("# hi", encoding="utf-8")
    cap_result = file_read_handler({"path": "doc.md"}, workspace_root=tmp_path)
    assert cap_result["success"] is True, cap_result.get("error")

    record = make_capability_record(
        event_type="ActionExecuted",
        payload={"action_kind": "file_read"},
        capability_result=cap_result,
    )
    assert record.provenance is not None
    assert record.provenance.url.startswith("file:")


def test_make_capability_record_none_for_side_effect_capability() -> None:
    """Capabilities without external source (e.g. shell_exec) leave provenance None."""
    cap_result = {"success": True, "stdout": "", "stderr": "", "returncode": 0}
    record = make_capability_record(
        event_type="ActionExecuted",
        payload={"action_kind": "shell_exec"},
        capability_result=cap_result,
    )
    assert record.provenance is None


def test_raw_memory_store_jsonl_persists_provenance(tmp_path: Path) -> None:
    """Provenance attached to a record survives JSONL round-trip."""
    store = RawMemoryStore(run_id="run-prov-1", base_dir=str(tmp_path))
    try:
        prov = Provenance(
            url="https://example.com/page",
            title="Page",
            source_type="web",
            retrieved_at="2026-04-22T00:00:00+00:00",
        )
        store.append(
            RawEventRecord(
                event_type="ActionExecuted",
                payload={"action_kind": "web_fetch"},
                provenance=prov,
            )
        )
    finally:
        store.close()

    log_path = tmp_path / "logs" / "memory" / "L0" / "run-prov-1.jsonl"
    line = log_path.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["metadata"]["provenance"]["url"] == "https://example.com/page"
    assert record["metadata"]["provenance"]["source_type"] == "web"


def test_raw_memory_store_jsonl_omits_provenance_when_none(tmp_path: Path) -> None:
    """Records without provenance do not add the provenance key to JSONL metadata."""
    store = RawMemoryStore(run_id="run-prov-2", base_dir=str(tmp_path))
    try:
        store.append(RawEventRecord(event_type="Tick", payload={"i": 0}))
    finally:
        store.close()
    log_path = tmp_path / "logs" / "memory" / "L0" / "run-prov-2.jsonl"
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "provenance" not in record["metadata"]


# Keep _io import referenced so the module stays lint-clean when expanded later.
_ = io.StringIO
