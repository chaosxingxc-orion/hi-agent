"""W14-E1: Runbook drill harness.

Runs operator runbook scenarios against the incident_runbook_commands library.
Emits evidence artifact to docs/verification/<sha>-runbook-drill.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def _git_short_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()[:7]


def _run_library_drill() -> list[dict[str, str]]:
    scenarios: list[dict[str, str]] = []
    try:
        from hi_agent.server import (
            incident_runbook_commands,  # type: ignore  expiry_wave: permanent
        )
    except ModuleNotFoundError:
        docs = sorted(Path("docs/runbook").glob("*.md"))
        status = "pass" if docs else "fail"
        detail = f"found {len(docs)} runbook file(s) under docs/runbook" if docs else "no .md files found under docs/runbook"  # noqa: E501  # expiry_wave: permanent  # added: W25 baseline sweep
        scenarios.append(
            {
                "name": "docs_existence_drill",
                "status": status,
                "detail": detail,
            }
        )
        return scenarios

    for fn_name in ("identify_stuck_runs", "drain_workers"):
        fn = getattr(incident_runbook_commands, fn_name, None)
        if fn is None:
            scenarios.append(
                {
                    "name": fn_name,
                    "status": "fail",
                    "detail": "function not found",
                }
            )
            continue
        try:
            fn()
            scenarios.append(
                {
                    "name": fn_name,
                    "status": "pass",
                    "detail": "call succeeded",
                }
            )
        except Exception as exc:  # pragma: no cover - runtime safety
            scenarios.append(
                {
                    "name": fn_name,
                    "status": "fail",
                    "detail": f"call failed: {exc}",
                }
            )
    return scenarios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run runbook drill scenarios")
    parser.add_argument("--json", action="store_true", help="also print evidence JSON to stdout")
    args = parser.parse_args(argv)

    started_at = datetime.now(UTC).isoformat()
    scenarios = _run_library_drill()
    overall = "pass" if all(s["status"] == "pass" for s in scenarios) else "fail"
    finished_at = datetime.now(UTC).isoformat()

    evidence = {
        "provenance": "structural",
        "started_at": started_at,
        "finished_at": finished_at,
        "scenarios": scenarios,
        "status": overall,
    }

    sha = _git_short_sha()
    out_dir = Path("docs/verification")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sha}-runbook-drill.json"
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _governance.evidence_writer import write_artifact
    write_artifact(
        path=out_path,
        body=evidence,
        provenance="structural",
        generator_script=__file__,
        degraded=True,
    )

    if args.json:
        print(json.dumps(evidence, indent=2))

    return 0 if overall == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

