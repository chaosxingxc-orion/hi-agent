"""Authoritative helper for writing governance evidence artifacts.

Every artifact that claims a score, gate status, or readiness number
must be written via write_artifact() so it carries full provenance metadata
and a paired *-provenance.json sidecar.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _get_head_sha() -> str:
    """Return 40-char HEAD SHA, or 'unknown' if git unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
            cwd=Path(__file__).resolve().parent.parent.parent,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def write_artifact(
    path: str | Path,
    body: dict,
    *,
    provenance: str,
    generator_script: str | None = None,
    requires_real_run_by: str | None = None,
    degraded: bool = False,
    overwrite: bool = True,
) -> Path:
    """Write evidence artifact with full provenance stamp and sidecar.

    Args:
        path: Output file path (e.g., docs/verification/foo.json).
        body: The artifact body (will be augmented with metadata).
        provenance: One of "real", "derived", "structural", "degraded", "dry_run".
                    If provenance != "real" and degraded=False, raises ValueError.
        generator_script: __file__ of the calling script. Auto-detected if None.
        requires_real_run_by: Wave by which a real-run must be recorded (e.g. next wave number).
        degraded: When True, permits non-real provenance without error.
        overwrite: When False, raises if the target already exists with provenance=real.
    """
    if provenance != "real" and not degraded:
        raise ValueError(
            f"write_artifact: provenance={provenance!r} is non-real. "
            "Pass degraded=True to explicitly allow, or fix the underlying mechanism."
        )

    if generator_script is None:
        # Walk the call stack to find the caller's __file__
        import inspect
        frame = inspect.currentframe()
        if frame and frame.f_back:
            generator_script = frame.f_back.f_globals.get("__file__", "unknown")
        else:
            generator_script = "unknown"

    head_sha = _get_head_sha()
    generated_at = datetime.now(timezone.utc).isoformat()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Build stamped body
    stamped = dict(body)
    stamped["_evidence_meta"] = {
        "provenance": provenance,
        "head_sha": head_sha,
        "generated_at": generated_at,
        "generator_script": str(generator_script),
    }
    if requires_real_run_by:
        stamped["_evidence_meta"]["requires_real_run_by"] = requires_real_run_by

    # Check existing
    if not overwrite and path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("_evidence_meta", {}).get("provenance") == "real":
                raise FileExistsError(
                    f"write_artifact: {path} already exists with provenance=real and overwrite=False"
                )
        except (json.JSONDecodeError, OSError):
            pass

    path.write_text(json.dumps(stamped, indent=2), encoding="utf-8")

    # Write sidecar provenance
    sidecar = path.with_name(path.stem + "-provenance.json")
    sidecar_body = {
        "artifact_path": str(path),
        "provenance": provenance,
        "head_sha": head_sha,
        "generated_at": generated_at,
        "generator_script": str(generator_script),
    }
    if requires_real_run_by:
        sidecar_body["requires_real_run_by"] = requires_real_run_by
    sidecar.write_text(json.dumps(sidecar_body, indent=2), encoding="utf-8")

    return path
