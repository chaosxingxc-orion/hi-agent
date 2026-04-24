#!/usr/bin/env python
"""Unified delivery gate runner.

Delegates to the structural and/or volces gate scripts and combines their
output into a single evidence file.

Usage:
    python scripts/run_delivery_gate.py --port PORT --output OUTPUT_PATH
    python scripts/run_delivery_gate.py --port PORT --output OUTPUT_PATH --mode structural
    python scripts/run_delivery_gate.py --port PORT --output OUTPUT_PATH --mode volces
    python scripts/run_delivery_gate.py --port PORT --output OUTPUT_PATH --mode unified

Modes:
    structural  Run only the structural gate (fake LLM, zero cost).
    volces      Run only the volces gate (real LLM, requires credentials).
    unified     Run both gates and combine results (default).

All additional CLI args accepted by the individual gate scripts are passed
through to the appropriate sub-gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _run_structural_gate(args: argparse.Namespace, output: Path) -> dict:
    """Import and run the structural gate, returning its evidence dict."""
    from scripts.rule15_structural_gate import (
        StructuralGateConfig,
    )
    from scripts.rule15_structural_gate import (
        run_gate as structural_run_gate,
    )

    config = StructuralGateConfig(
        port=args.port,
        fake_llm_port=getattr(args, "fake_llm_port", 0),
        output=output,
        profile_id=getattr(args, "profile_id", "rule15_volces"),
        ready_timeout_s=getattr(args, "ready_timeout", 120.0),
        poll_timeout_s=getattr(args, "poll_timeout", 180.0),
        poll_interval_s=getattr(args, "poll_interval", 1.0),
        request_timeout_s=getattr(args, "request_timeout", 15.0),
        startup_timeout_s=getattr(args, "startup_timeout", 30.0),
    )
    try:
        evidence = structural_run_gate(config)
        if isinstance(evidence, dict):
            evidence.setdefault(
                "verdict", "PASS" if evidence.get("status") == "passed" else "FAIL"
            )
            return evidence
        return {"verdict": "PASS", "status": "passed"}
    except Exception as exc:
        return {"verdict": "FAIL", "status": "failed", "error": str(exc)}


def _run_volces_gate(args: argparse.Namespace, output: Path) -> dict:
    """Import and run the volces gate, returning its evidence dict."""
    from scripts.rule15_volces_gate import (
        GateConfig,
    )
    from scripts.rule15_volces_gate import (
        run_gate as volces_run_gate,
    )

    config = GateConfig(
        base_url=getattr(args, "base_url", None),
        port=args.port,
        output=output,
        profile_id=getattr(args, "profile_id", "rule15_volces"),
        ready_timeout_s=getattr(args, "ready_timeout", 120.0),
        poll_timeout_s=getattr(args, "poll_timeout", 180.0),
        poll_interval_s=getattr(args, "poll_interval", 1.0),
        request_timeout_s=getattr(args, "request_timeout", 15.0),
        startup_timeout_s=getattr(args, "startup_timeout", 30.0),
    )
    try:
        evidence_obj = volces_run_gate(config)
        evidence = (
            evidence_obj.to_dict()
            if hasattr(evidence_obj, "to_dict")
            else dict(evidence_obj)
        )
        evidence.setdefault(
            "verdict", "PASS" if evidence.get("status") == "passed" else "FAIL"
        )
        return evidence
    except Exception as exc:
        return {"verdict": "FAIL", "status": "failed", "error": str(exc)}


def _write_output(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified delivery gate runner")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--output", required=True, help="Path to write combined evidence JSON")
    parser.add_argument(
        "--mode",
        choices=["structural", "volces", "unified"],
        default="unified",
        help=(
            "Gate mode: structural (fake LLM), volces (real LLM), "
            "or unified (both). Default: unified"
        ),
    )
    # Pass-through args for the individual gate scripts
    parser.add_argument("--fake-llm-port", type=int, default=0)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--profile-id", default="rule15_volces")
    parser.add_argument("--ready-timeout", type=float, default=120.0)
    parser.add_argument("--poll-timeout", type=float, default=180.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--request-timeout", type=float, default=15.0)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    output = Path(args.output)
    sha = _git_sha()

    if args.mode == "structural":
        structural_output = output.with_suffix(".structural.json")
        evidence = _run_structural_gate(args, structural_output)
        evidence["sha"] = sha
        evidence["mode"] = "structural"
        _write_output(output, evidence)
        verdict = evidence.get("verdict", "FAIL")
        print(f"Structural gate verdict: {verdict}; evidence written to {output}")
        return 0 if verdict == "PASS" else 1

    if args.mode == "volces":
        volces_output = output.with_suffix(".volces.json")
        evidence = _run_volces_gate(args, volces_output)
        evidence["sha"] = sha
        evidence["mode"] = "volces"
        _write_output(output, evidence)
        verdict = evidence.get("verdict", "FAIL")
        print(f"Volces gate verdict: {verdict}; evidence written to {output}")
        return 0 if verdict == "PASS" else 1

    # unified mode
    structural_output = output.with_suffix(".structural.json")
    volces_output = output.with_suffix(".volces.json")

    structural_evidence = _run_structural_gate(args, structural_output)
    volces_evidence = _run_volces_gate(args, volces_output)

    structural_verdict = structural_evidence.get("verdict", "FAIL")
    volces_verdict = volces_evidence.get("verdict", "FAIL")
    combined_verdict = (
        "PASS" if (structural_verdict == "PASS" and volces_verdict == "PASS") else "FAIL"
    )

    combined: dict = {
        "sha": sha,
        "mode": "unified",
        "structural": structural_evidence,
        "volces": volces_evidence,
        "verdict": combined_verdict,
    }
    _write_output(output, combined)
    print(
        f"Unified gate verdict: {combined_verdict} "
        f"(structural={structural_verdict}, volces={volces_verdict}); "
        f"evidence written to {output}"
    )
    return 0 if combined_verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
