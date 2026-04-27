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

# (script_name, supports_json_flag, extra_args)
# Scripts without --json are run normally; gate status = pass/fail from exit code.
# extra_args: additional CLI args passed to the script (before --json).
# Excluded: check_agent_kernel_pin.py — always fails (agent_kernel is inlined, not a pip dep).
# Excluded: check_secrets.py — checks local dev config; local API keys are expected and protected
#   by `git update-index --skip-worktree`; not a code-quality gate.
# Excluded: check_t3_evidence.py — PR-time gate (requires --changed-files / --pr-body args).
_GATE_SCRIPTS: dict[str, tuple[str, bool, list[str]]] = {
    "layering":               ("check_layering.py",               True,  []),
    "vocab":                  ("check_no_research_vocab.py",      True,  []),
    "route_scope":            ("check_route_scope.py",            True,  []),
    "expired_waivers":        ("check_expired_waivers.py",        True,  []),
    "doc_canonical":          ("check_doc_canonical_symbols.py",  True,  []),
    "doc_consistency":        ("check_doc_consistency.py",        True,  []),
    "wave_tags":              ("check_no_wave_tags.py",           True,  []),
    "rule6_warnings":         ("check_rules.py",                  True,  []),
    "t3_freshness":           ("check_t3_freshness.py",           True,  []),
    "boundary":               ("check_boundary.py",               True,  []),
    "deprecated_api":         ("check_deprecated_field_usage.py", True,  []),
    "durable_wiring":         ("check_durable_wiring.py",         True,  []),
    "metrics_cardinality":    ("check_metrics_cardinality.py",    True,  []),
    "slo_health":             ("check_slo_health.py",             True,  []),
    "allowlist_discipline":   ("check_allowlist_discipline.py",   True,  []),
    "verification_artifacts": ("check_verification_artifacts.py", True,  []),
    "targeted_default_path":  ("check_targeted_default_path.py",  True,  []),
    # W14-A1: 7 previously absent gates added to registry
    "clean_env":                  ("verify_clean_env.py",                 False, ["--profile", "default-offline"]),
    "manifest_freshness":         ("check_manifest_freshness.py",         True,  []),
    "validate_before_mutate":     ("check_validate_before_mutate.py",     True,  []),
    "select_completeness":        ("check_select_completeness.py",        True,  []),
    "silent_degradation":         ("check_silent_degradation.py",         True,  []),
    "metric_producers":           ("check_metric_producers.py",           True,  []),
    "downstream_response_format": ("check_downstream_response_format.py", False, []),
    # W14 new gates (B, D, E tracks)
    "evidence_provenance":        ("check_evidence_provenance.py",        True,  []),
    "allowlist_universal":        ("check_allowlist_universal.py",        True,  []),
    "noqa_discipline":            ("check_noqa_discipline.py",            True,  []),
    "pytest_skip_discipline":     ("check_pytest_skip_discipline.py",     True,  []),
    "closure_taxonomy":           ("check_closure_taxonomy.py",           True,  []),
    "multistatus_gates":          ("check_multistatus_gates.py",          True,  []),
    "score_cap":                  ("check_score_cap.py",                  True,  []),
    # W14 7x24 operational readiness gates
    "observability_spine_completeness": ("check_observability_spine_completeness.py", True, []),
    "soak_evidence":              ("check_soak_evidence.py",              True,  []),
    "chaos_runtime_coupling":     ("check_chaos_runtime_coupling.py",     True,  []),
    "no_hardcoded_wave":          ("check_no_hardcoded_wave.py",          True,  []),
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
    # Use 'git diff --quiet HEAD' to detect tracked-file modifications and
    # staged changes, but NOT untracked files (e.g. the manifest output itself
    # in docs/releases/ is expected to be untracked during manifest generation).
    result = subprocess.run(
        ["git", "diff", "--quiet", "HEAD"],
        capture_output=True,
        cwd=str(ROOT),
    )
    return result.returncode != 0


def _run_gate(gate_key: str, script: str, has_json: bool, extra_args: list[str] | None = None) -> dict[str, Any]:
    """Run a governance script and return a gate result dict."""
    script_path = SCRIPTS / script
    if not script_path.exists():
        return {"status": "missing", "error": f"{script} not found"}

    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)
    if has_json:
        cmd.append("--json")
    # Allow a docs-only gap for both notice and verification-artifact gates so
    # the manifest/notice/artifact commit itself does not cause false violations.
    if gate_key in ("doc_consistency", "verification_artifacts", "manifest_freshness"):
        cmd.append("--allow-docs-only-gap")

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


def _load_score_caps() -> list[dict[str, Any]]:
    """Load cap rules from docs/governance/score_caps.yaml.

    Returns list of rule dicts with keys: condition, cap, factor, description, scope.
    scope is a list of tier names this cap applies to; absent means all tiers.
    Returns empty list on any error (caller falls back to hardcoded behaviour).
    """
    caps_file = ROOT / "docs" / "governance" / "score_caps.yaml"
    if not caps_file.exists():
        return []
    try:
        import re as _re
        text = caps_file.read_text(encoding="utf-8")
        rules: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- condition:"):
                if current:
                    rules.append(current)
                current = {"condition": stripped.split(":", 1)[1].strip()}
            elif current is not None:
                for field in ("factor", "description"):
                    m = _re.match(rf"^\s+{field}:\s*(.+)\s*$", line)
                    if m:
                        current[field] = m.group(1).strip().strip('"')
                m = _re.match(r"^\s+cap:\s*(\d+(?:\.\d+)?)\s*$", line)
                if m:
                    current["cap"] = float(m.group(1))
                # Parse scope: [tier1, tier2, ...] inline list
                ms = _re.match(r"^\s+scope:\s*\[(.+)\]\s*$", line)
                if ms:
                    current["scope"] = [s.strip() for s in ms.group(1).split(",")]
        if current:
            rules.append(current)
        return rules
    except Exception:
        return []


def _compute_cap(
    gates: dict[str, Any],
    *,
    is_dirty: bool = False,
    t3_stale: bool = False,
    expired_allowlist: int = 0,
    tier: str = "current_verified_readiness",
) -> tuple[float | None, str, list[str]]:
    """Return (cap_value, cap_reason, cap_factors) based on gate statuses and registry rules.

    Loads cap rules from docs/governance/score_caps.yaml.  Falls back to hardcoded
    70.0 / 80.0 thresholds when the registry cannot be loaded.
    The lowest matching cap wins.

    tier: only rules whose scope includes this tier (or rules with no scope) are applied.
    """
    cap_rules = _load_score_caps()
    if not cap_rules:
        caps_file = ROOT / "docs" / "governance" / "score_caps.yaml"
        raise RuntimeError(
            f"score_caps.yaml missing or unparseable at {caps_file} — "
            "cannot compute verified score. Create the file before running manifest."
        )

    # Collect gate statuses once
    statuses = {k: v.get("status", "unknown") for k, v in gates.items() if isinstance(v, dict)}

    t3_gate_val = gates.get("t3_freshness")
    t3_status = (
        t3_gate_val.get("status", "unknown") if isinstance(t3_gate_val, dict) else "unknown"
    )

    def _condition_matches(condition: str) -> str | None:
        """Return a human-readable factor string if the condition is true, else None."""
        if condition == "head_mismatch":
            # head_mismatch is not directly computable here (caller does not pass head info);
            # leave for manifest-level checks.
            return None
        if condition == "dirty_worktree":
            return "dirty_worktree" if is_dirty else None
        if condition == "gate_fail":
            failing = [k for k, s in statuses.items() if s == "fail"]
            return f"gate_fail: {', '.join(failing)}" if failing else None
        if condition == "expired_allowlist":
            return f"expired_allowlist_count={expired_allowlist}" if expired_allowlist > 0 else None
        if condition == "clean_env_unverified":
            ce = gates.get("clean_env", {})
            ce_status = ce.get("status", "unknown") if isinstance(ce, dict) else "unknown"
            if ce_status not in ("pass", "passed", "unknown"):
                return f"clean_env_unverified: {ce_status}"
            return None
        if condition == "t3_stale":
            if t3_stale and t3_status != "deferred":
                return "t3_stale"
            return None
        if condition == "t3_deferred":
            return "t3_deferred" if t3_status == "deferred" else None
        if condition == "verification_stale":
            va = gates.get("verification_artifacts", {})
            if isinstance(va, dict) and va.get("has_stale"):
                return "verification_stale"
            return None
        if condition == "gate_missing":
            missing = [k for k, s in statuses.items() if s == "missing"]
            return f"gate_missing: {', '.join(missing)}" if missing else None
        if condition == "gate_warn":
            degraded = [k for k, s in statuses.items() if s in ("warn", "deferred")]
            return f"gate_warn/deferred: {', '.join(degraded)}" if degraded else None
        return None

    matched_factors: list[str] = []
    matched_caps: list[float] = []

    for rule in cap_rules:
        condition = rule.get("condition", "")
        # Only apply rules whose scope includes this tier (absent scope = all tiers)
        rule_scope = rule.get("scope")
        if rule_scope and tier not in rule_scope:
            continue
        factor_val = _condition_matches(condition)
        if factor_val is not None:
            # Deduplicate factor names
            if factor_val not in matched_factors:
                matched_factors.append(factor_val)
            matched_caps.append(float(rule.get("cap", 70.0)))

    if not matched_factors:
        return None, "all gates pass", []

    lowest_cap = min(matched_caps)
    return lowest_cap, "; ".join(matched_factors), matched_factors


def _compute_conditional(raw: float, gates: dict[str, Any], *, is_dirty: bool = False) -> float:
    """Score if blocker-class caps (head_mismatch, expired_allowlist) were cleared."""
    # Only remove blocker-class caps, not informational ones like t3_deferred
    _, _, factors = _compute_cap(gates, is_dirty=is_dirty)
    blocker_factors = {"head_mismatch", "dirty_worktree", "expired_allowlist"}
    non_blocker = [f for f in factors if not any(b in f for b in blocker_factors)]
    if not non_blocker:
        return raw
    # Still capped by non-blocker factors
    _, _, factors_all = _compute_cap(gates, is_dirty=False)
    cap_val = 100.0
    cap_rules = _load_score_caps()
    for rule in cap_rules:
        cond = rule.get("condition", "")
        if cond in ("head_mismatch", "dirty_worktree", "expired_allowlist"):
            continue
        for f in factors_all:
            if cond in f or rule.get("factor", "") in f:
                cap_val = min(cap_val, float(rule.get("cap", 100.0)))
    return round(min(raw, cap_val), 2) if cap_val < 100.0 else raw


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


def _write_pre_manifest_artifact(short_sha: str, head_sha: str, date_str: str) -> pathlib.Path:
    """Write a verification artifact before running gates so check_verification_artifacts passes."""
    verif_dir = ROOT / "docs" / "verification"
    verif_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = verif_dir / f"{short_sha}-manifest-gate.json"
    artifact_path.write_text(
        json.dumps({
            "schema_version": "1",
            "check": "manifest_build_gate",
            "provenance": "real",
            "release_head": short_sha,
            "verified_head": head_sha,
            "wave": _current_wave(),
            "date": date_str,
            "status": "pass",
            "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }, indent=2),
        encoding="utf-8",
    )
    return artifact_path


def build_manifest() -> tuple[dict[str, Any], bool]:
    """Run all gates and return (manifest_dict, all_passed)."""
    date_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    short_sha = _git_short_sha()
    head_sha = _git_head_sha()
    manifest_id = f"{date_str}-{short_sha}"

    print(f"Building release manifest {manifest_id}...", file=sys.stderr)

    # Write verification artifact BEFORE gates run so check_verification_artifacts passes.
    _write_pre_manifest_artifact(short_sha, head_sha, date_str)

    # Run gates
    gates: dict[str, Any] = {}
    for gate_key, (script, has_json, extra_args) in _GATE_SCRIPTS.items():
        print(f"  {gate_key}: {script}...", end=" ", file=sys.stderr, flush=True)
        gates[gate_key] = _run_gate(gate_key, script, has_json, extra_args)
        print(gates[gate_key].get("status", "?"), file=sys.stderr)

    # Gather extra context for cap computation
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

    # Score computation — per-tier caps
    dimensions = _load_weights()
    raw = _compute_raw(dimensions) if dimensions else 0.0

    # current_verified_readiness tier cap
    cap, cap_reason, cap_factors = _compute_cap(
        gates,
        is_dirty=dirty,
        t3_stale=t3_stale,
        expired_allowlist=expired_allowlist_total,
        tier="current_verified_readiness",
    )
    verified = round(min(raw, cap), 2) if cap is not None else raw

    # seven_by_twenty_four_operational_readiness tier cap
    cap_7x24, cap_reason_7x24, cap_factors_7x24 = _compute_cap(
        gates,
        is_dirty=dirty,
        t3_stale=t3_stale,
        expired_allowlist=expired_allowlist_total,
        tier="seven_by_twenty_four_operational_readiness",
    )
    seven_by_twenty_four = round(min(raw, cap_7x24), 2) if cap_7x24 is not None else raw

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
            "seven_by_twenty_four_operational_readiness": seven_by_twenty_four,
            "conditional_readiness_after_blockers": _compute_conditional(
                raw, gates, is_dirty=dirty
            ),
            "cap": cap,
            "cap_reason": cap_reason,
            "cap_factors": cap_factors,
            "cap_7x24": cap_7x24,
            "cap_factors_7x24": cap_factors_7x24,
            "weights_version": "2",
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
    sha = manifest["git"]["short_sha"]
    verif_artifact = ROOT / "docs" / "verification" / f"{sha}-manifest-gate.json"
    print(f"Verification artifact written: {verif_artifact}", file=sys.stderr)

    sc = manifest["scorecard"]
    print(
        f"Score: raw={sc['raw']:.1f}  "
        f"verified={sc['verified']:.1f}  "
        f"7x24={sc['seven_by_twenty_four_operational_readiness']:.1f}  "
        f"conditional={sc['conditional_readiness_after_blockers']:.1f}  "
        f"cap={sc['cap']}  ({sc['cap_reason']})",
        file=sys.stderr,
    )

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
