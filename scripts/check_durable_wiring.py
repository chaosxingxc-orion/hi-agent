#!/usr/bin/env python3
"""CI gate: every SQLite-backed class must be wired in app.py (or explicitly exempted).

Scans hi_agent/**/*.py for classes with _CREATE_TABLE or sqlite3.connect at class level.
Each such class must either:
  (a) appear in hi_agent/server/app.py constructor calls, OR
  (b) have a '# scope: process-internal' comment in its source file.

Also verifies all requires_durable_* posture knobs are referenced in app.py/_durable_backends.py.

The --json flag additionally runs an in-process runtime probe that instantiates
each durable-store class and verifies basic protocol compliance.
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _governance_json import emit_result

ROOT = Path(__file__).parent.parent


def find_sqlite_classes() -> list[tuple[Path, str]]:
    results = []
    for path in ROOT.glob("hi_agent/**/*.py"):
        src = path.read_text(encoding="utf-8")
        if "_CREATE_TABLE" not in src and "sqlite3.connect" not in src:
            continue
        # Check for process-internal exemption
        if "# scope: process-internal" in src:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                body_src = ast.get_source_segment(src, node) or ""
                if "_CREATE_TABLE" in body_src or "sqlite3.connect" in body_src:
                    results.append((path, node.name))
    return results


def check_wired_in_app(class_name: str) -> bool:
    app_path = ROOT / "hi_agent" / "server" / "app.py"
    backends_path = ROOT / "hi_agent" / "server" / "_durable_backends.py"
    for p in (app_path, backends_path):
        if p.exists() and class_name in p.read_text(encoding="utf-8"):
            return True
    return False


def check_posture_knobs_referenced() -> list[str]:
    posture_path = ROOT / "hi_agent" / "config" / "posture.py"
    posture_src = posture_path.read_text(encoding="utf-8")
    knob_pattern = re.compile(r"def (requires_durable_\w+)")
    knobs = knob_pattern.findall(posture_src)
    try:
        app_src = (ROOT / "hi_agent" / "server" / "app.py").read_text(encoding="utf-8")
    except Exception as exc:
        print(f"FAIL durable_wiring: could not read app.py: {exc}", file=sys.stderr)
        app_src = None  # will cause check to fail rather than silently degrade
    backends_src_path = ROOT / "hi_agent" / "server" / "_durable_backends.py"
    backends_src = (
        backends_src_path.read_text(encoding="utf-8") if backends_src_path.exists() else ""
    )
    if app_src is None:
        # Return all knobs as dead since we could not read app.py.
        return list(knobs)
    dead = []
    for knob in knobs:
        if knob not in app_src and knob not in backends_src:
            dead.append(knob)
    return dead


def _runtime_probe() -> dict[str, Any]:
    """Instantiate each durable-store class and verify basic protocol compliance."""
    sys.path.insert(0, str(ROOT))
    results: dict[str, Any] = {}

    # Probe SQLiteEventStore
    try:
        from hi_agent.server.event_store import SQLiteEventStore, StoredEvent

        store = SQLiteEventStore(":memory:")
        event = StoredEvent(
            event_id=str(uuid.uuid4()),
            run_id="probe-run",
            sequence=0,
            event_type="probe",
            payload_json="{}",
        )
        store.append(event)
        events = store.list_since("probe-run", -1)
        assert len(events) >= 1, "list_since returned no events after append"
        assert store.max_sequence("probe-run") == 0
        store.close()
        results["SQLiteEventStore"] = "pass"
    except Exception as exc:
        results["SQLiteEventStore"] = f"fail: {exc}"

    # Probe SQLiteRunStore (if available)
    try:
        from hi_agent.server.run_store import SQLiteRunStore

        store = SQLiteRunStore(":memory:")
        results["SQLiteRunStore"] = "pass"
    except Exception as exc:
        results["SQLiteRunStore"] = f"fail: {exc}"

    # Probe IdempotencyStore (if available)
    try:
        from hi_agent.server.idempotency import IdempotencyStore

        store = IdempotencyStore(":memory:")
        results["IdempotencyStore"] = "pass"
    except Exception as exc:
        results["IdempotencyStore"] = f"fail: {exc}"

    return results


def _parse_wiring_error(text: str) -> dict:
    """Parse an error string into a structured dict."""
    # Format: "  file::ClassName 鈥?message"
    m = re.match(r"\s+([^:]+)::(\w+)\s+\xe2\x80\x94\s+(.*)", text)
    if m is None:
        m = re.match(r"\s+([^:]+)::(\w+)\s+--\s+(.*)", text)
    if m:
        return {"file": m.group(1), "class": m.group(2), "text": m.group(3)}
    return {"text": text.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check durable wiring")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output instead of human-readable text.",
    )
    args = parser.parse_args()

    errors = []
    sqlite_classes = find_sqlite_classes()
    for path, cls_name in sqlite_classes:
        if not check_wired_in_app(cls_name):
            errors.append(
                f"  {path.relative_to(ROOT)}::{cls_name} 鈥?not wired in app.py/_durable_backends.py"
                " (add construction or '# scope: process-internal')"
            )
    dead_knobs = check_posture_knobs_referenced()
    for knob in dead_knobs:
        errors.append(
            f"  posture.py::{knob} 鈥?knob never referenced in"
            " app.py or _durable_backends.py (dead code)"
        )

    if args.json:
        probe_results = _runtime_probe()
        probe_failures = [
            f"{cls}: {msg}" for cls, msg in probe_results.items() if str(msg).startswith("fail:")
        ]
        structured = [_parse_wiring_error(e) for e in errors]
        all_pass = not errors and not probe_failures
        emit_result(
            "durable_wiring",
            "pass" if all_pass else "fail",
            violations=structured,
            counts={"classes_checked": len(sqlite_classes)},
            extra={"runtime_probe": probe_results, "probe_failures": probe_failures},
        )
        # emit_result calls sys.exit, so the lines below are unreachable when --json.
        return 0  # pragma: no cover

    if errors:
        print("FAIL check_durable_wiring:")
        for e in errors:
            print(e)
        return 1
    print("OK check_durable_wiring")
    return 0


if __name__ == "__main__":
    sys.exit(main())

