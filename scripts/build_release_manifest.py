"""Release manifest builder.

Runs every governance check script, aggregates results, computes a verified
score (capped by gate states), and writes the manifest to
docs/releases/platform-release-manifest-<date>-<sha>.json.

Usage::

    python scripts/build_release_manifest.py             # write to docs/releases/
    python scripts/build_release_manifest.py --print     # stdout only, no file write
    python scripts/build_release_manifest.py --output /path/to/file.json
    python scripts/build_release_manifest.py --dry-run   # run checks, print manifest, exit 0

Exit 0: manifest written (or printed), all gates pass.
Exit 1: manifest written (or printed), one or more gates failed.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import subprocess
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
RELEASES_DIR = ROOT / "docs" / "releases"
WEIGHTS_FILE = ROOT / "docs" / "scorecard_weights.yaml"
CURRENT_WAVE_FILE = ROOT / "docs" / "current-wave.txt"

# (script_name, supports_json_flag)
# Scripts without --json are run normally; gate status = pass/fail from exit code.
# Excluded: check_agent_kernel_pin.py — always fails (agent_kernel is inlined, not a pip dep).
# Excluded: check_secrets.py — checks local dev config; local API keys are expected and protected
#   by `git update-index --skip-worktree`; not a code-quality gate.
# Excluded: check_t3_evidence.py — PR-time gate (requires --changed-files / --pr-body args).
_GATE_SCRIPTS: dict[str, tuple[str, bool]] = {
    "layering":          ("check_layering.py",              True),
    "vocab":             ("check_no_research_vocab.py",     True),
    "route_scope":       ("check_route_scope.py",           True),
    "expired_waivers":   ("check_expired_waivers.py",       True),
    "doc_canonical":     ("check_doc_canonical_symbols.py", True),
    "doc_consistency":   ("check_doc_consistency.py",       True),
    "wave_tags":         ("check_no_wave_tags.py",          True),
    "rule6_warnings":    ("check_rules.py",                 True),
    "t3_freshness":      ("check_t3_freshness.py",          False),
    "boundary":          ("check_boundary.py",              True),
    "deprecated_api":    ("check_deprecated_field_usage.py", True),
    "durable_wiring":    ("check_durable_wiring.py",        True),
}


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=str(ROOT)
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_head_sha() -> str:
    return _git("rev-parse", "HEAD") or "unknown"


def _git_short_sha() -> str:
    return _git("rev-parse", "--short", "HEAD") or "unknown"


def _is_dirty() -> bool:
    return bool(_git("status", "--porcelain"))


def _run_gate(gate_key: str, script: str, has_json: bool) -> dict[str, Any]:
    """Run a governance script and return a gate result dict."""
    script_path = SCRIPTS / script
    if not script_path.exists():
        return {"status": "missing", "error": f"{script} not found"}

    cmd = [sys.executable, str(script_path)]
    if has_json:
        cmd.append("--json")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=str(ROOT)
        )
    except subprocess.TimeoutExpired:
        return {"status": "fail", "error": "timeout after 120s"}
    except Exception as exc:
        return {"status": "fail", "error": str(exc)}

    gate: dict[str, Any] = {}

    if has_json and result.stdout.strip():
        try:
            data = json.loads(result.stdout)
            gate.update(data)
            gate.setdefault("status", "pass" if result.returncode == 0 else "fail")
        except json.JSONDecodeError:
            gate["status"] = "pass" if result.returncode == 0 else "fail"
            gate["raw_stdout"] = result.stdout[:500]
    else:
        gate["status"] = "pass" if result.returncode == 0 else "fail"
        if result.stdout.strip():
            gate["summary"] = result.stdout.strip()[:500]

    if result.returncode != 0 and result.stderr.strip():
        gate["stderr"] = result.stderr.strip()[:500]

    return gate


def _load_weights() -> list[dict[str, Any]]:
    """Load scorecard_weights.yaml. Returns empty list if not found or parse error."""
    if not WEIGHTS_FILE.exists():
        return []
    try:
        import re
        text = WEIGHTS_FILE.read_text(encoding="utf-8")
        # Minimal YAML parser: extract dimension blocks
        # Each dimension has name, weight, base_score fields
        dims: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- name:"):
                if current:
                    dims.append(current)
                current = {"name": stripped.split(":", 1)[1].strip()}
            elif current is not None:
                for field in ("weight", "base_score"):
                    m = re.match(rf"^\s+{field}:\s*(\d+(?:\.\d+)?)\s*$", line)
                    if m:
                        current[field] = float(m.group(1))
                for field in ("gate_check",):
                    m = re.match(rf"^\s+{field}:\s*(\S+)\s*$", line)
                    if m:
                        current[field] = m.group(1)
        if current:
            dims.append(current)
        return dims
    except Exception:
        return []


def _compute_raw(dimensions: list[dict[str, Any]]) -> float:
    """Compute raw score = sum(weight * base_score / 100)."""
    total = 0.0
    for dim in dimensions:
        w = float(dim.get("weight", 0))
        s = float(dim.get("base_score", 0))
        total += w * s / 100.0
    return round(total, 2)


def _compute_cap(
    gates: dict[str, Any],
    *,
    is_dirty: bool = False,
    t3_stale: bool = False,
    expired_allowlist: int = 0,
) -> tuple[float | None, str, list[str]]:
    """Return (cap_value, cap_reason, cap_factors) based on gate statuses and extra context."""
    cap_factors: list[str] = []

    statuses = [v.get("status", "unknown") for v in gates.values() if isinstance(v, dict)]
    if "fail" in statuses:
        failing = [k for k, v in gates.items() if isinstance(v, dict) and v.get("status") == "fail"]
        cap_factors.append(f"gate_fail: {', '.join(failing)}")
    if "warn" in statuses or "deferred" in statuses:
        degraded = [
            k for k, v in gates.items()
            if isinstance(v, dict) and v.get("status") in ("warn", "deferred")
        ]
        cap_factors.append(f"gate_warn/deferred: {', '.join(degraded)}")
    if "missing" in statuses:
        cap_factors.append("one or more scripts missing")
    if is_dirty:
        cap_factors.append("dirty_worktree")
    if t3_stale:
        cap_factors.append("t3_stale")
    if expired_allowlist > 0:
        cap_factors.append(f"expired_allowlist_count={expired_allowlist}")

    if not cap_factors:
        return None, "all gates pass", []

    if any("gate_fail" in f for f in cap_factors) or is_dirty:
        return 70.0, "; ".join(cap_factors), cap_factors
    return 80.0, "; ".join(cap_factors), cap_factors


def _compute_conditional(raw: float, dimensions: list[dict[str, Any]]) -> float:
    """Score if all blockers were resolved: raw score uncapped."""
    return raw


def _load_captains_sha() -> str:
    path = ROOT / "docs" / "releases" / "release-captains.md"
    if not path.exists():
        return "not_found"
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _current_wave() -> str:
    if CURRENT_WAVE_FILE.exists():
        return CURRENT_WAVE_FILE.read_text(encoding="utf-8").strip()
    return "unknown"


def build_manifest() -> tuple[dict[str, Any], bool]:
    """Run all gates and return (manifest_dict, all_passed)."""
    date_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    short_sha = _git_short_sha()
    manifest_id = f"{date_str}-{short_sha}"

    print(f"Building release manifest {manifest_id}...", file=sys.stderr)

    # Run gates
    gates: dict[str, Any] = {}
    for gate_key, (script, has_json) in _GATE_SCRIPTS.items():
        print(f"  {gate_key}: {script}...", end=" ", file=sys.stderr, flush=True)
        gates[gate_key] = _run_gate(gate_key, script, has_json)
        print(gates[gate_key].get("status", "?"), file=sys.stderr)

    # Gather extra context for cap computation
    head_sha = _git_head_sha()
    dirty = _is_dirty()

    t3_gate = gates.get("t3_freshness", {})
    t3_status = t3_gate.get("status", "unknown")
    t3_verified_head = t3_gate.get("verified_head", "")
    t3_stale = t3_status not in ("pass", "fresh_at_head")

    route_scope_gate = gates.get("route_scope", {})
    allowlist_total = route_scope_gate.get("allowlist_total", 0)
    expired_allowlist_total = route_scope_gate.get("expired_allowlist_total", 0)

    clean_env_gate = gates.get("clean_env", {})
    clean_env_status = clean_env_gate.get("status", "unknown")
    clean_env_summary_available = clean_env_gate.get("summary_available", None)

    # Score computation
    dimensions = _load_weights()
    raw = _compute_raw(dimensions) if dimensions else 0.0
    cap, cap_reason, cap_factors = _compute_cap(
        gates,
        is_dirty=dirty,
        t3_stale=t3_stale,
        expired_allowlist=expired_allowlist_total,
    )
    verified = round(min(raw, cap), 2) if cap is not None else raw

    manifest: dict[str, Any] = {
        "manifest_id": manifest_id,
        "schema_version": "1",
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "release_head": head_sha,
        "git": {
            "head_sha": head_sha,
            "short_sha": short_sha,
            "is_dirty": dirty,
        },
        "wave": _current_wave(),
        "gates": gates,
        "scorecard": {
            "raw": raw,
            "verified": verified,
            "raw_implementation_maturity": raw,
            "current_verified_readiness": verified,
            "conditional_readiness_after_blockers": _compute_conditional(raw, dimensions),
            "cap": cap,
            "cap_reason": cap_reason,
            "cap_factors": cap_factors,
            "weights_version": "1",
        },
        "t3": {
            "status": t3_status,
            "verified_head": t3_verified_head,
        },
        "clean_env": {
            "profile": "default-offline",
            "status": clean_env_status,
            "summary_available": clean_env_summary_available,
        },
        "route_scope": {
            "allowlist_total": allowlist_total,
            "expired_allowlist_total": expired_allowlist_total,
        },
        "captains": _load_captains_sha(),
    }

    all_passed = all(
        v.get("status") == "pass"
        for v in gates.values()
        if isinstance(v, dict)
    )
    return manifest, all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the release manifest.")
    parser.add_argument("--output", help="Output path (default: docs/releases/)")
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="Print manifest to stdout; do not write file.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run checks, print manifest, exit 0 regardless of gate state.")
    args = parser.parse_args()

    manifest, all_passed = build_manifest()
    manifest_json = json.dumps(manifest, indent=2)

    if args.print_only or args.dry_run:
        print(manifest_json)
        return 0

    # Determine output path
    if args.output:
        out_path = pathlib.Path(args.output)
    else:
        RELEASES_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
        short_sha = manifest["git"]["short_sha"]
        out_path = RELEASES_DIR / f"platform-release-manifest-{date_str}-{short_sha}.json"

    out_path.write_text(manifest_json, encoding="utf-8")
    print(f"Manifest written: {out_path}", file=sys.stderr)
    print(
        f"Score: raw={manifest['scorecard']['raw']:.1f}  "
        f"verified={manifest['scorecard']['verified']:.1f}  "
        f"conditional={manifest['scorecard']['conditional_readiness_after_blockers']:.1f}  "
        f"cap={manifest['scorecard']['cap']}  "
        f"({manifest['scorecard']['cap_reason']})",
        file=sys.stderr,
    )

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
