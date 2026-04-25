#!/usr/bin/env python3
"""CI gate: every SQLite-backed class must be wired in app.py (or explicitly exempted).

Scans hi_agent/**/*.py for classes with _CREATE_TABLE or sqlite3.connect at class level.
Each such class must either:
  (a) appear in hi_agent/server/app.py constructor calls, OR
  (b) have a '# scope: process-internal' comment in its source file.

Also verifies all requires_durable_* posture knobs are referenced in app.py/_durable_backends.py.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

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
    app_src = (ROOT / "hi_agent" / "server" / "app.py").read_text(encoding="utf-8")
    backends_src_path = ROOT / "hi_agent" / "server" / "_durable_backends.py"
    backends_src = (
        backends_src_path.read_text(encoding="utf-8") if backends_src_path.exists() else ""
    )
    dead = []
    for knob in knobs:
        if knob not in app_src and knob not in backends_src:
            dead.append(knob)
    return dead


def main() -> int:
    errors = []
    sqlite_classes = find_sqlite_classes()
    for path, cls_name in sqlite_classes:
        if not check_wired_in_app(cls_name):
            errors.append(
                f"  {path.relative_to(ROOT)}::{cls_name} — not wired in app.py/_durable_backends.py"
                " (add construction or '# scope: process-internal')"
            )
    dead_knobs = check_posture_knobs_referenced()
    for knob in dead_knobs:
        errors.append(
            f"  posture.py::{knob} — knob never referenced in"
            " app.py or _durable_backends.py (dead code)"
        )
    if errors:
        print("FAIL check_durable_wiring:")
        for e in errors:
            print(e)
        return 1
    print("OK check_durable_wiring")
    return 0


if __name__ == "__main__":
    sys.exit(main())
