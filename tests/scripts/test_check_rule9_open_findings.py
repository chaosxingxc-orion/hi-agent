"""Tests for scripts/check_rule9_open_findings.py (W32-D D.6 gate).

Covers (per task spec):
  - Empty log → pass.
  - OPEN finding in a ship-blocking category → fail.
  - OPEN in a non-blocking category → pass.
  - CLOSED in any category → pass.
  - Real repository ``docs/rules-incident-log.md`` at HEAD → pass.
  - JSON CLI shape.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest  # noqa: F401  # expiry_wave: permanent

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "check_rule9_open_findings.py"
sys.path.insert(0, str(ROOT / "scripts"))
import check_rule9_open_findings as gate


def _run_gate(log_path: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", "--log-path", str(log_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    payload: dict = {}
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {"raw_stdout": proc.stdout, "raw_stderr": proc.stderr}
    return proc.returncode, payload


def test_empty_log_passes(tmp_path: Path) -> None:
    """An empty log file yields zero findings → exit 0."""
    log = tmp_path / "rules-incident-log.md"
    log.write_text("", encoding="utf-8")
    rc, payload = _run_gate(log)
    assert rc == 0, payload
    assert payload["status"] == "pass"
    assert payload["open_blocking_total"] == 0


def test_open_finding_in_ship_blocking_category_fails(tmp_path: Path) -> None:
    """An OPEN finding under one of the six ship-blocking categories must fail."""
    log = tmp_path / "rules-incident-log.md"
    log.write_text(
        "# Rules Incident Log\n\n"
        "## Open Findings\n\n"
        "- Status: OPEN — LLM path — async client recreated per call leaks loops\n"
        "- Status: OPEN — Run lifecycle — cancellation does not propagate to subrun\n",
        encoding="utf-8",
    )
    rc, payload = _run_gate(log)
    assert rc == 1, payload
    assert payload["status"] == "fail"
    assert payload["open_blocking_total"] == 2
    categories = sorted({f["category"] for f in payload["open_findings"]})
    assert categories == ["LLM path", "Run lifecycle"]


def test_open_finding_in_non_blocking_category_passes(tmp_path: Path) -> None:
    """An OPEN finding under a non-blocking category (e.g. doc-truth, vocabulary) is allowed.

    Per Rule 9, only the six listed ship-blocking categories block delivery.
    A finding tagged with a category outside that vocabulary is not gated by
    this script.
    """
    log = tmp_path / "rules-incident-log.md"
    log.write_text(
        "# Rules Incident Log\n\n"
        "## Open Findings\n\n"
        "- Status: OPEN — Doc truth — capability-matrix.md timestamp lag\n"
        "- Status: OPEN — Vocabulary debt — leftover research term in CLI help\n",
        encoding="utf-8",
    )
    rc, payload = _run_gate(log)
    assert rc == 0, payload
    assert payload["status"] == "pass"
    assert payload["open_blocking_total"] == 0


def test_closed_finding_in_any_category_passes(tmp_path: Path) -> None:
    """A CLOSED finding in any category — including ship-blocking ones — passes."""
    log = tmp_path / "rules-incident-log.md"
    log.write_text(
        "# Rules Incident Log\n\n"
        "## Closed Findings\n\n"
        "- Status: CLOSED — LLM path — async client lifetime fixed in W23 Track C\n"
        "- Status: CLOSED — Security boundary — path traversal closed in W19\n"
        "- Status: CLOSED — Doc truth — matrix refreshed W32-D\n",
        encoding="utf-8",
    )
    rc, payload = _run_gate(log)
    assert rc == 0, payload
    assert payload["status"] == "pass"
    assert payload["open_blocking_total"] == 0


def test_mixed_open_and_closed_only_open_blocking_counts(tmp_path: Path) -> None:
    """A mix: only OPEN ship-blocking findings count toward fail."""
    log = tmp_path / "rules-incident-log.md"
    log.write_text(
        "# Rules Incident Log\n\n"
        "- Status: CLOSED — LLM path — fixed long ago\n"
        "- Status: OPEN — Doc truth — non-blocking category\n"
        "- Status: OPEN — HTTP contract — missing 404 path\n"
        "- Status: OPEN — Observability — fallback emits no metric\n",
        encoding="utf-8",
    )
    rc, payload = _run_gate(log)
    assert rc == 1, payload
    assert payload["status"] == "fail"
    assert payload["open_blocking_total"] == 2
    cats = sorted({f["category"] for f in payload["open_findings"]})
    assert cats == ["HTTP contract", "Observability"]


def test_real_repo_passes_at_head() -> None:
    """The real ``docs/rules-incident-log.md`` at HEAD passes Rule 9."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"check_rule9_open_findings failed at HEAD\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    payload = json.loads(proc.stdout)
    assert payload["status"] == "pass", payload
    assert payload["open_blocking_total"] == 0


def test_missing_log_is_deferred(tmp_path: Path) -> None:
    """A missing log file → exit 2 (deferred), not exit 1 (fail)."""
    nonexistent = tmp_path / "no-such-file.md"
    rc, payload = _run_gate(nonexistent)
    assert rc == 2, payload
    assert payload["status"] == "deferred"


def test_cli_json_output_shape() -> None:
    """`--json` must emit a parseable JSON document with the expected keys."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(proc.stdout)
    assert "check" in payload and payload["check"] == "rule9_open_findings"
    assert "status" in payload
    assert "open_blocking_total" in payload
    assert "open_findings" in payload
    assert isinstance(payload["open_findings"], list)
    assert "ship_blocking_categories" in payload
    assert len(payload["ship_blocking_categories"]) == 6


def test_classify_category_recognises_all_six() -> None:
    """Each documented ship-blocking category is recognised by classifier."""
    examples = [
        ("LLM path", "LLM path"),
        ("llm-path", "LLM path"),
        ("Run lifecycle", "Run lifecycle"),
        ("run_lifecycle", "Run lifecycle"),
        ("HTTP contract", "HTTP contract"),
        ("http-contract", "HTTP contract"),
        ("Security boundary", "Security boundary"),
        ("Resource lifetime", "Resource lifetime"),
        ("Observability", "Observability"),
        ("observability", "Observability"),
    ]
    for token, expected in examples:
        assert gate._classify_category(token) == expected, (token, expected)


def test_classify_category_rejects_non_blocking() -> None:
    """Non-blocking category labels return None."""
    for token in ("Doc truth", "Vocabulary debt", "Test honesty", "Hygiene"):
        assert gate._classify_category(token) is None, token
