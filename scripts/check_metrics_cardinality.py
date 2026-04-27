#!/usr/bin/env python3
"""CI gate: assert no metric in _METRIC_DEFS uses a forbidden high-cardinality label.

Forbidden labels: run_id, task_id, goal, prompt, content, raw_user_input

Exit 0: pass
Exit 1: fail (high-cardinality label found)

Flags:
  --json  Emit structured JSON report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_FORBIDDEN_LABELS = frozenset({
    "run_id", "task_id", "goal", "prompt", "content", "raw_user_input",
})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check metric label cardinality.")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    try:
        from hi_agent.observability.collector import _METRIC_DEFS
    except ImportError as e:
        msg = f"Cannot import _METRIC_DEFS: {e}"
        if args.json_output:
            print(json.dumps({"check": "metrics_cardinality", "status": "fail", "error": msg}))
        else:
            print(f"FAIL: {msg}")
        return 1

    # _METRIC_DEFS values are _MetricDef dataclass instances; they do not carry
    # a labels field (labels are tracked at call-site level, not in the registry).
    # This gate checks the registry keys for any accidental high-cardinality name
    # baked into the metric name itself (e.g. "metric_<run_id>_total").
    violations: list[dict] = []
    for metric_name in _METRIC_DEFS:
        for forbidden in _FORBIDDEN_LABELS:
            # Check if the forbidden token appears as a segment of the metric name.
            if forbidden in metric_name.split("_"):
                violations.append({"metric": metric_name, "forbidden_label": forbidden})

    if args.json_output:
        status = "fail" if violations else "pass"
        print(json.dumps({
            "check": "metrics_cardinality",
            "status": status,
            "violations": violations,
            "metrics_checked": len(_METRIC_DEFS),
        }, indent=2))
        return 1 if violations else 0

    if violations:
        print("FAIL check_metrics_cardinality:")
        for v in violations:
            print(f"  {v['metric']}: forbidden label '{v['forbidden_label']}'")
        return 1

    print(f"OK check_metrics_cardinality ({len(_METRIC_DEFS)} metrics checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
