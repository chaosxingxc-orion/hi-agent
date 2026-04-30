#!/usr/bin/env python3
"""W14-C2/Soak evidence gate.

Reads the latest soak evidence from docs/verification/*-soak-*.json or
docs/delivery/*-soak-*.json. Status semantics:

    pass        — provenance==real AND duration_seconds>=86400 AND invariants_held
                  (full 24h soak; lifts the 7x24 cap entirely)
    partial_1h  — provenance==real AND duration_seconds>=3600 AND invariants_held
                  (1h soak; partial credit — lifts 7x24 cap from 65 to 80
                  via the soak_24h_pending condition in score_caps.yaml)
    deferred    — real soak < 1h, dry_run, or shape_1h provenance
                  (soak_24h_missing condition fires; cap stays at 65)
    fail        — synthetic/unknown provenance OR unreadable evidence

Exit codes:
    0  — pass, partial_1h, or deferred (all non-blocking; manifest scoring
         translates each into the right cap factor)
    1  — fail (blocking)

Note on invariants:
    Older soak evidence (pre-W24) does not carry invariants_held; for backwards
    compatibility a missing key is treated as True so historical 24h pilot
    evidence continues to score correctly. New soak evidence emitted by
    `scripts/run_soak.py` always populates the key.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"
DELIVERY_DIR = ROOT / "docs" / "delivery"

_MIN_24H_SECONDS = 86400  # 24 hours
_MIN_1H_SECONDS = 3600    # 1 hour


def _latest_soak_evidence() -> pathlib.Path | None:
    """Pick latest soak evidence from either verification or delivery directories.

    Sort logic delegated to _governance.evidence_picker — single source of truth
    that uses (generated_at, mtime, name).

    Provenance sidecars (``*-provenance.json``) are filtered out: they describe
    the provenance of a sibling artifact, they are NOT the artifact itself.
    """
    from _governance.evidence_picker import all_evidence

    def _pick(directory: pathlib.Path) -> pathlib.Path | None:
        for p in reversed(all_evidence(directory, "*soak*.json")):
            if not p.name.endswith("-provenance.json"):
                return p
        return None

    a = _pick(VERIF_DIR)
    b = _pick(DELIVERY_DIR)
    if a and b:
        try:
            return a if a.stat().st_mtime >= b.stat().st_mtime else b
        except OSError:
            return a
    return a or b


def _emit(args: argparse.Namespace, payload: dict, *, exit_code: int) -> int:
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        status = payload.get("status", "unknown")
        reason = payload.get("reason", "")
        if status == "pass":
            print(f"PASS: {reason or 'real 24h soak evidence present'}")
        elif status == "partial_1h":
            print(f"PARTIAL_1H: {reason or 'real 1h soak evidence present'}")
        elif status == "fail":
            print(f"FAIL: {reason}", file=sys.stderr)
        else:
            print(f"DEFERRED: {reason}", file=sys.stderr)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Soak evidence gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    soak_file = _latest_soak_evidence()
    if soak_file is None:
        return _emit(
            args,
            {
                "status": "deferred",
                "check": "soak_evidence",
                "reason": "no soak evidence found (1h or 24h soak required)",
            },
            exit_code=0,
        )

    try:
        data = json.loads(soak_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _emit(
            args,
            {
                "status": "fail",
                "check": "soak_evidence",
                "reason": f"unreadable: {exc}",
                "evidence_file": soak_file.name,
            },
            exit_code=1,
        )

    provenance = data.get("provenance", "unknown")
    duration = data.get("duration_seconds", 0)
    mode = data.get("mode", "")
    # Backwards compat: pre-W24 evidence has no invariants_held key; treat missing
    # as True so historical 24h pilots still score correctly.
    invariants_held = data.get("invariants_held", True)

    base_payload: dict = {
        "check": "soak_evidence",
        "provenance": provenance,
        "duration_seconds": duration,
        "invariants_held": invariants_held,
        "evidence_file": soak_file.name,
    }

    # ── synthetic / unknown ──────────────────────────────────────────────
    if provenance in ("synthetic", "unknown"):
        return _emit(
            args,
            {
                **base_payload,
                "status": "fail",
                "reason": f"soak evidence has provenance:{provenance} — not accepted",
            },
            exit_code=1,
        )

    # ── dry_run / shape_1h / shape_verified — deferred ───────────────────
    if (
        provenance in ("dry_run", "shape_1h", "shape_verified", "pilot_run")
        or mode == "dry_run"
    ):
        return _emit(
            args,
            {
                **base_payload,
                "status": "deferred",
                "reason": (
                    f"soak provenance is '{provenance}' "
                    "(harness-validation only; real 1h or 24h soak required for credit)"
                ),
            },
            exit_code=0,
        )

    # ── invariants must hold for any 'real' credit ───────────────────────
    if provenance == "real" and not invariants_held:
        return _emit(
            args,
            {
                **base_payload,
                "status": "deferred",
                "reason": (
                    f"soak ran for {duration}s with provenance:real but "
                    "invariants did NOT hold; cannot grant credit"
                ),
            },
            exit_code=0,
        )

    # ── full 24h pass ────────────────────────────────────────────────────
    if provenance == "real" and duration >= _MIN_24H_SECONDS:
        return _emit(
            args,
            {
                **base_payload,
                "status": "pass",
                "reason": f"real 24h soak evidence present ({int(duration)}s)",
            },
            exit_code=0,
        )

    # ── partial 1h credit ────────────────────────────────────────────────
    if provenance == "real" and duration >= _MIN_1H_SECONDS:
        return _emit(
            args,
            {
                **base_payload,
                "status": "partial_1h",
                "reason": (
                    f"real 1h soak evidence present ({int(duration)}s); "
                    "24h soak still pending — partial credit"
                ),
            },
            exit_code=0,
        )

    # ── real but < 1h — deferred ─────────────────────────────────────────
    return _emit(
        args,
        {
            **base_payload,
            "status": "deferred",
            "reason": (
                f"real soak duration {int(duration)}s < {_MIN_1H_SECONDS}s "
                "(1h credit threshold)"
            ),
        },
        exit_code=0,
    )


if __name__ == "__main__":
    sys.exit(main())
