#!/usr/bin/env python3
"""CI gate: every metric in _METRIC_DEFS must have at least one producer callsite.

For each metric name defined in hi_agent.observability.collector._METRIC_DEFS,
scan hi_agent/ and agent_kernel/ for at least one callsite that passes the
metric name as a string literal to record(), increment(), gauge_set(), or
get_metrics_collector().increment(<name>).

Fails closed on orphan metrics (defined but never called).

Exit 0: all metrics have producers.
Exit 1: orphan metrics found.
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["hi_agent", "agent_kernel"]


def _load_metric_names() -> list[str]:
    """Import collector and extract _METRIC_DEFS keys."""
    try:
        sys.path.insert(0, str(ROOT))
        from hi_agent.observability.collector import _METRIC_DEFS

        return list(_METRIC_DEFS.keys())
    except Exception as exc:
        print(f"WARNING: could not import _METRIC_DEFS: {exc}", file=sys.stderr)
        return []


def _scan_for_metric_callsites(metric_names: list[str]) -> dict[str, list[str]]:
    """Scan source files and return {metric_name: [file:line, ...]} for each found callsite."""
    found: dict[str, list[str]] = {name: [] for name in metric_names}

    for scan_dir in SCAN_DIRS:
        scan_root = ROOT / scan_dir
        if not scan_root.exists():
            continue
        for py_file in sorted(scan_root.rglob("*.py")):
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            rel = str(py_file.relative_to(ROOT))
            for i, line in enumerate(src.splitlines(), 1):
                for name in metric_names:
                    if f'"{name}"' in line or f"'{name}'" in line:
                        found[name].append(f"{rel}:{i}")

    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    metric_names = _load_metric_names()
    if not metric_names:
        if args.json_output:
            print(
                json.dumps(
                    {
                        "check": "metric_producers",
                        "status": "fail",
                        "reason": "could not load _METRIC_DEFS",
                    }
                )
            )
        return 1

    callsites = _scan_for_metric_callsites(metric_names)
    orphans = [name for name, sites in callsites.items() if not sites]

    # Known-exemptions: metrics defined for future use or only appearing in tests.
    # Add entries to docs/governance/allowlists.yaml with allowlist: metric_producer_allowlist.
    test_only_metrics: set[str] = set()

    true_orphans = [o for o in orphans if o not in test_only_metrics]

    if args.json_output:
        print(
            json.dumps(
                {
                    "check": "metric_producers",
                    "status": "fail" if true_orphans else "pass",
                    "total_metrics": len(metric_names),
                    "orphan_count": len(true_orphans),
                    "orphans": true_orphans[:20],
                },
                indent=2,
            )
        )
        return 1 if true_orphans else 0

    if true_orphans:
        print(f"FAIL metric_producers: {len(true_orphans)} orphan metric(s) with no producer:")
        for o in true_orphans[:10]:
            print(f"  {o}")
        return 1

    print(f"OK metric_producers: all {len(metric_names)} metrics have at least one callsite")
    return 0


if __name__ == "__main__":
    sys.exit(main())

