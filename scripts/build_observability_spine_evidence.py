"""Build observability-spine evidence for the release manifest.

Checks that RunExecutionContext and ManagedRun carry the required correlation
spine fields (trace_id equivalent, run_id, tenant_id, user_id, session_id).

Emits docs/verification/<sha>-observability-spine.json and exits 0 on success,
non-zero on any missing required field.

Usage:
    python scripts/build_observability_spine_evidence.py
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure repo root is importable when run as a script (python scripts/...)
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

REQUIRED_SPINE_FIELDS = ["run_id", "tenant_id", "user_id", "session_id"]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _get_field_names(cls: type) -> list[str]:
    """Return field names for a dataclass."""
    return [f.name for f in dataclasses.fields(cls)]


def main() -> int:
    sha = _git_sha()
    generated_at = _iso_now()

    # Import the classes under test
    try:
        from hi_agent.context.run_execution_context import RunExecutionContext
    except ImportError as exc:
        print(f"ERROR: cannot import RunExecutionContext: {exc}", file=sys.stderr)
        return 1

    try:
        from hi_agent.server.run_manager import ManagedRun
    except ImportError as exc:
        print(f"ERROR: cannot import ManagedRun: {exc}", file=sys.stderr)
        return 1

    rec_fields = _get_field_names(RunExecutionContext)
    mr_fields = _get_field_names(ManagedRun)

    spine_coverage = {
        "RunExecutionContext": rec_fields,
        "ManagedRun": mr_fields,
    }

    # Check required fields
    missing: dict[str, list[str]] = {}
    for cls_name, fields in spine_coverage.items():
        absent = [f for f in REQUIRED_SPINE_FIELDS if f not in fields]
        if absent:
            missing[cls_name] = absent

    status = "pass" if not missing else "fail"

    evidence = {
        "release_head": sha,
        "generated_at": generated_at,
        "spine_fields_checked": REQUIRED_SPINE_FIELDS,
        "spine_coverage": spine_coverage,
        "missing_fields": missing,
        "status": status,
    }

    # Write evidence file
    script_dir = Path(__file__).parent
    out_dir = script_dir.parent / "docs" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sha}-observability-spine.json"
    out_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    if missing:
        print(f"FAIL: missing spine fields: {missing}", file=sys.stderr)
        print(f"Evidence written to {out_path}")
        return 1

    print(f"OK: observability-spine evidence written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
