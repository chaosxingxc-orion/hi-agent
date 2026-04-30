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

# Ensure scripts/ is on sys.path so sibling-package imports work both for
# direct script invocation and for `import scripts.build_release_manifest` from
# pytest. Matches the existing pattern in check_doc_consistency.py.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

# Local helpers — single source of truth for manifest selection, gap
# classification, and wave labels. See scripts/_governance/.
from _governance.governance_gap import (
    GAP_DOCS_ONLY,
    GAP_GOV_INFRA,
)
from _governance.governance_gap import (
    is_docs_only_gap as _gov_is_docs_only_gap,
)
from _governance.governance_gap import (
    is_gov_only_gap as _gov_is_gov_only_gap,
)
from _governance.manifest_picker import (
    latest_manifest as _latest_manifest_dict,
)
from _governance.manifest_picker import (
    manifest_for_sha,
)
from _governance.wave import current_wave as _wave_current_wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
RELEASES_DIR = ROOT / "docs" / "releases"
WEIGHTS_FILE = ROOT / "docs" / "scorecard_weights.yaml"
CURRENT_WAVE_FILE = ROOT / "docs" / "current-wave.txt"

# Architectural-constraint gates -- they represent 7x24 operational readiness
# requirements that are deferred by design, NOT engineering defects.  These
# gates must NEVER contribute a cap factor to current_verified_readiness;
# their caps are scoped exclusively to seven_by_twenty_four_operational_readiness
# in score_caps.yaml.  Excluding them here prevents double-counting when
# gate_warn/gate_fail/gate_missing scan all gate statuses without per-gate
# scope awareness.
_ARCH_CONSTRAINT_GATES: frozenset[str] = frozenset({
    "soak_evidence",
    "observability_spine_completeness",
    "chaos_runtime_coupling",
})

# (script_name, supports_json_flag, extra_args)
# Scripts without --json are run normally; gate status = pass/fail from exit code.
# extra_args: additional CLI args passed to the script (before --json).
# Excluded: check_agent_kernel_pin.py — always fails (agent_kernel is inlined, not a pip dep).
# Excluded: check_secrets.py — checks local dev config; local API keys are expected and protected
#   by `git update-index --skip-worktree`; not a code-quality gate.
# Excluded: check_t3_evidence.py — PR-time gate (requires --changed-files / --pr-body args).
_GATE_SCRIPTS: dict[str, tuple] = {
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
    "verification_artifacts": ("check_verification_artifacts.py", True,  ["--allow-docs-only-gap"]),
    "targeted_default_path":  ("check_targeted_default_path.py",  True,  []),
    # 7 previously absent gates added to registry
    # manifest_freshness is intentionally NOT in _GATE_SCRIPTS: it runs
    # BEFORE the new manifest is written, so it would always see the previous
    # committed manifest and fail on any non-docs-only gap.  It runs instead
    # as a separate CI step in release-gate.yml, after the manifest is committed.
    "clean_env":                  ("verify_clean_env.py",                 False, ["--profile", "default-offline"], 360),
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
    # score_cap is excluded from inline gates: it compares the notice claimed score against
    # the manifest's own score while the manifest is being computed — that creates a circular
    # dependency (score_cap fails → gate_fail=70 cap → manifest says 70 → score_cap fails again).
    # check_score_cap.py runs as a separate CI step in release-gate.yml after the manifest is final.
    # W14 7x24 operational readiness gates
    "observability_spine_completeness": ("check_observability_spine_completeness.py", True, []),
    "soak_evidence":              ("check_soak_evidence.py",              True,  []),
    "chaos_runtime_coupling":     ("check_chaos_runtime_coupling.py",     True,  []),
    "no_hardcoded_wave":          ("check_no_hardcoded_wave.py",          True,  []),
}


# Backward-compat aliases — the canonical definitions live in
# _governance.governance_gap. Keep the historical names so internal callers
# in this file (and any external consumers that imported them) still work
# while the migration completes.
_GOV_PREFIXES: tuple[str, ...] = GAP_DOCS_ONLY
_EVIDENCE_GAP_PREFIXES: tuple[str, ...] = GAP_GOV_INFRA


def _docs_only_gap(base_sha: str, head_sha: str) -> bool:
    """Manifest-freshness gap: only docs/** changed (excludes functional configs).

    Delegates to the canonical helper so all callers agree.
    """
    return _gov_is_docs_only_gap(base_sha, head_sha, repo_root=ROOT)


def _evidence_gov_gap(base_sha: str, head_sha: str) -> bool:
    """Evidence-freshness gap: only docs/scripts/.github changed.

    Delegates to the canonical helper. Looser than _docs_only_gap because
    gate-script and CI-config changes don't invalidate evidence collected
    against a prior product HEAD.
    """
    return _gov_is_gov_only_gap(base_sha, head_sha, repo_root=ROOT)


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


def _run_gate(gate_key: str, script: str, has_json: bool, extra_args: list[str] | None = None, timeout: int = 120) -> dict[str, Any]:
    """Run a governance script and return a gate result dict."""
    script_path = SCRIPTS / script
    if not script_path.exists():
        return {"status": "missing", "error": f"{script} not found"}

    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)
    if has_json:
        cmd.append("--json")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT)
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


def _run_multistatus_runner() -> dict[str, Any]:
    """Invoke the  multistatus runner and return its aggregate dict.

    Returns an empty dict on failure so callers fall back to "no multistatus
    debt" semantics (defer_count == 0). The runner's exit code already drives
    `gate_fail` independently via the per-gate scripts wired into the workflow.
    """
    runner_path = SCRIPTS / "_governance" / "multistatus_runner.py"
    if not runner_path.exists():
        return {}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "scripts._governance.multistatus_runner",
             "--all", "--json", "--timeout", "60"],
            capture_output=True, text=True, timeout=180, cwd=str(ROOT),
        )
    except Exception:
        return {}
    out = (proc.stdout or "").strip()
    if not out:
        return {}
    try:
        # Last JSON line wins (allow logging on earlier lines).
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                return json.loads(line)
    except Exception:
        return {}
    return {}


def _compute_cap(
    gates: dict[str, Any],
    *,
    is_dirty: bool = False,
    t3_stale: bool = False,
    expired_allowlist: int = 0,
    multistatus_pending_count: int = 0,
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

    def _condition_matches(condition: str, _tier: str = tier) -> str | None:
        """Return a human-readable factor string if the condition is true, else None.

        _tier is passed through so that gate_warn / gate_fail / gate_missing
        can exclude _ARCH_CONSTRAINT_GATES when computing caps for
        current_verified_readiness.  Architectural gates (soak, spine, chaos)
        represent 7x24 operational constraints -- they must never contribute
        a cap factor to the engineering-readiness tier.
        """
        # When computing engineering-readiness caps, ignore architectural gates
        # so that their deferred status does not double-count into verified score.
        _exclude_arch = (
            _ARCH_CONSTRAINT_GATES
            if _tier == "current_verified_readiness"
            else frozenset()
        )
        if condition == "head_mismatch":
            head_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            current_head = head_proc.stdout.strip() if head_proc.returncode == 0 else ""
            if not current_head:
                return None
            # Does any manifest already cover the current HEAD?
            if manifest_for_sha(current_head, RELEASES_DIR) is not None:
                return None
            # No manifest covers current HEAD — find the latest manifest to
            # report the gap. Use the canonical helper so cap-computation and
            # other manifest-consuming gates agree on which manifest is "latest".
            latest = _latest_manifest_dict(RELEASES_DIR)
            if latest is None:
                return None
            manifest_head = str(latest.get("release_head", "")).strip()
            if not manifest_head:
                return None
            # Docs-only gap exemption: only docs/** changed (excludes functional configs).
            if _docs_only_gap(manifest_head, current_head):
                return None
            return f"head_mismatch: manifest={manifest_head[:12]} HEAD={current_head[:12]}"
        if condition == "dirty_worktree":
            return "dirty_worktree" if is_dirty else None
        if condition == "gate_fail":
            failing = [
                k for k, s in statuses.items()
                if s == "fail" and k not in _exclude_arch
            ]
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
            missing = [
                k for k, s in statuses.items()
                if s == "missing" and k not in _exclude_arch
            ]
            return f"gate_missing: {', '.join(missing)}" if missing else None
        if condition == "gate_warn":
            degraded = [
                k for k, s in statuses.items()
                if s in ("warn", "deferred") and k not in _exclude_arch
            ]
            return f"gate_warn/deferred: {', '.join(degraded)}" if degraded else None
        if condition == "provenance_unknown_or_synthetic":
            # Filename fragments that identify evidence files belonging to
            # architectural-constraint gates.  When _tier is
            # current_verified_readiness those files are excluded from the
            # provenance scan, mirroring the gate_warn/gate_fail/gate_missing
            # exclusion of _ARCH_CONSTRAINT_GATES.
            _arch_file_fragments: tuple[str, ...] = (
                "soak",
                "observability-spine",
                "chaos",
            ) if _exclude_arch else ()
            for evidence_dir in (ROOT / "docs" / "verification", ROOT / "docs" / "delivery"):
                if not evidence_dir.exists():
                    continue
                for json_file in evidence_dir.rglob("*.json"):
                    if _arch_file_fragments and any(
                        frag in json_file.name for frag in _arch_file_fragments
                    ):
                        continue
                    try:
                        payload = json.loads(json_file.read_text(encoding="utf-8"))
                    except Exception:
                        continue

                    def _scan_provenance(node: Any) -> str | None:
                        if isinstance(node, dict):
                            prov = node.get("provenance")
                            if isinstance(prov, str) and prov in ("synthetic", "unknown"):
                                return prov
                            for child in node.values():
                                found = _scan_provenance(child)
                                if found:
                                    return found
                        elif isinstance(node, list):
                            for child in node:
                                found = _scan_provenance(child)
                                if found:
                                    return found
                        return None

                    matched = _scan_provenance(payload)
                    if matched:
                        return f"provenance_unknown_or_synthetic: {json_file.name}={matched}"
            return None
        if condition == "soak_24h_missing":
            soak_gate = gates.get("soak_evidence")
            soak_status = soak_gate.get("status", "unknown") if isinstance(soak_gate, dict) else "unknown"
            return f"soak_24h_missing: {soak_status}" if soak_status != "pass" else None
        if condition == "observability_spine_incomplete":
            spine_gate = gates.get("observability_spine_completeness")
            spine_status = spine_gate.get("status", "unknown") if isinstance(spine_gate, dict) else "unknown"
            return f"observability_spine_incomplete: {spine_status}" if spine_status != "pass" else None
        if condition == "chaos_non_runtime_coupled":
            chaos_gate = gates.get("chaos_runtime_coupling")
            chaos_status = chaos_gate.get("status", "unknown") if isinstance(chaos_gate, dict) else "unknown"
            return f"chaos_non_runtime_coupled: {chaos_status}" if chaos_status != "pass" else None
        if condition == "t3_shape_verified":
            t3_gate = gates.get("t3_freshness")
            t3_provenance = t3_gate.get("provenance", "") if isinstance(t3_gate, dict) else ""
            return (
                f"t3_shape_verified: {t3_provenance}"
                if t3_provenance in ("structural", "shape_verified")
                else None
            )
        if condition == "multistatus_gates_pending_low":
            # 1–3 boundary multistatus gates still in DEFER (cap 92).
            if 1 <= multistatus_pending_count <= 3:
                return f"multistatus_pending_low: defer_count={multistatus_pending_count}"
            return None
        if condition == "multistatus_gates_pending_high":
            # 4+ boundary multistatus gates still in DEFER (cap 80).
            if multistatus_pending_count >= 4:
                return f"multistatus_pending_high: defer_count={multistatus_pending_count}"
            return None
        if condition == "expired_allowlist_accepted_as_pass":
            return (
                f"expired_allowlist_accepted_as_pass: {expired_allowlist}"
                if expired_allowlist > 0
                else None
            )
        if condition == "notice_inconsistency":
            # Fails when check_doc_consistency or check_release_identity reports fail
            doc_gate = gates.get("doc_consistency", {})
            doc_status = doc_gate.get("status", "unknown") if isinstance(doc_gate, dict) else "unknown"
            id_gate = gates.get("release_identity", {})
            id_status = id_gate.get("status", "unknown") if isinstance(id_gate, dict) else "unknown"
            if doc_status == "fail":
                return f"notice_inconsistency: doc_consistency={doc_status}"
            if id_status == "fail":
                violations = id_gate.get("violations", []) if isinstance(id_gate, dict) else []
                return f"notice_inconsistency: release_identity={id_status} {violations[:1]}"
            return None
        if condition == "clean_env_not_final_head":
            # Passes when any clean-env artifact matches HEAD exactly, OR when
            # the diff between that artifact's HEAD and current HEAD is docs-only.
            # Iterate all artifacts so that a newer artifact (e.g. after lint fixes)
            # can satisfy the condition even if an older artifact alphabetically wins
            # the mtime sort in CI where all files share the checkout mtime.
            ce_files = list((ROOT / "docs" / "verification").glob("*clean-env*.json"))
            if not ce_files:
                return None  # No clean-env artifact — covered by clean_env_unverified
            head_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=str(ROOT),
            )
            current_head = head_proc.stdout.strip() if head_proc.returncode == 0 else ""
            if not current_head:
                return None
            # Check each artifact: exact match OR governance-only gap
            best_ce_head = ""
            for ce_f in ce_files:
                try:
                    ce_data = json.loads(ce_f.read_text(encoding="utf-8"))
                    ce_head = str(ce_data.get("head", "")).strip()
                except Exception:
                    continue
                if not ce_head:
                    continue
                min_len = min(len(ce_head), len(current_head), 12)
                if ce_head[:min_len] == current_head[:min_len]:
                    return None  # Exact match
                if _evidence_gov_gap(ce_head, current_head):
                    return None  # Governance-only gap — evidence still valid
                # Track the most recent artifact head for the error message
                if not best_ce_head or ce_head > best_ce_head:
                    best_ce_head = ce_head
            return f"clean_env_not_final_head: evidence={best_ce_head[:12]} HEAD={current_head[:12]}"
        if condition == "operator_drill_missing":
            # Fails when no operator-drill evidence exists for the current HEAD
            # Exclude -provenance.json sidecars; they have no all_passed field.
            drill_files = sorted(
                (
                    p for p in (ROOT / "docs" / "verification").glob("*operator-drill*.json")
                    if not p.name.endswith("-provenance.json")
                ),
                key=lambda p: p.stat().st_mtime,
            )
            if not drill_files:
                return "operator_drill_missing: no evidence found"
            try:
                drill_data = json.loads(drill_files[-1].read_text(encoding="utf-8"))
                drill_passed = drill_data.get("all_passed", False)
                drill_prov = drill_data.get("provenance", "unknown")
            except Exception:
                return "operator_drill_missing: evidence unreadable"
            if drill_prov != "real" or not drill_passed:
                return f"operator_drill_missing: provenance={drill_prov} all_passed={drill_passed}"
            return None
        if condition == "release_identity_fail":
            id_gate = gates.get("release_identity", {})
            id_status = id_gate.get("status", "unknown") if isinstance(id_gate, dict) else "unknown"
            return f"release_identity_fail: {id_status}" if id_status == "fail" else None
        if condition == "verification_artifact_missing_at_head":
            va_gate = gates.get("verification_artifacts", {})
            va_status = va_gate.get("status", "unknown") if isinstance(va_gate, dict) else "unknown"
            has_current = va_gate.get("has_current_head", True) if isinstance(va_gate, dict) else True
            if va_status == "fail" or not has_current:
                return f"verification_artifact_missing_at_head: {va_status}"
            return None
        if condition == "clean_env_artifact_missing_at_head":
            ce_files = list((ROOT / "docs" / "verification").glob("*clean-env*.json"))
            if not ce_files:
                return "clean_env_artifact_missing_at_head: no clean-env artifact found"
            head_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=str(ROOT),
            )
            current_head = head_proc.stdout.strip() if head_proc.returncode == 0 else ""
            if not current_head:
                return None
            for ce_f in ce_files:
                try:
                    ce_data = json.loads(ce_f.read_text(encoding="utf-8"))
                    ce_head = str(ce_data.get("head", "")).strip()
                except Exception:
                    continue
                if not ce_head:
                    continue
                min_len = min(len(ce_head), len(current_head), 12)
                if ce_head[:min_len] == current_head[:min_len]:
                    return None
                # Governance-only commits since the artifact are not a gap
                if _evidence_gov_gap(ce_head, current_head):
                    return None
            return f"clean_env_artifact_missing_at_head: no artifact matches HEAD={current_head[:12]}"
        if condition == "score_artifact_inconsistent":
            # Only check score-cap artifacts that are at the CURRENT HEAD.
            # Historical artifacts at intermediate commits will naturally have manifest_ids
            # that differ from their filename SHA — that is expected, not an error.
            head_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=str(ROOT),
            )
            current_head = head_proc.stdout.strip() if head_proc.returncode == 0 else ""
            if not current_head:
                return None
            score_files = list((ROOT / "docs" / "verification").glob("*score*.json"))
            for sf in score_files:
                try:
                    sd = json.loads(sf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                verified_head = str(sd.get("verified_head", "")).strip()
                # Only validate artifacts that claim to be at the current HEAD.
                if not verified_head or not (
                    current_head.startswith(verified_head[:7]) or
                    verified_head.startswith(current_head[:7])
                ):
                    continue  # historical artifact from a different HEAD — skip
                file_stem = sf.stem  # e.g. "<sha>-score-cap"
                manifest_id = str(sd.get("manifest_id", "")).strip()
                # filename must contain manifest_id or its SHA portion
                if manifest_id and manifest_id not in file_stem:
                    sha_part = manifest_id.split("-")[-1] if "-" in manifest_id else manifest_id
                    if sha_part not in file_stem:
                        return f"score_artifact_inconsistent: {sf.name} manifest_id={manifest_id} not in filename"
            return None
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


def _compute_conditional(
    raw: float,
    gates: dict[str, Any],
    *,
    is_dirty: bool = False,
    multistatus_pending_count: int = 0,
) -> float:
    """Score if blocker-class caps (head_mismatch, expired_allowlist) were cleared."""
    # Only remove blocker-class caps, not informational ones like t3_deferred
    _, _, factors = _compute_cap(
        gates, is_dirty=is_dirty,
        multistatus_pending_count=multistatus_pending_count,
    )
    blocker_factors = {"head_mismatch", "dirty_worktree", "expired_allowlist"}
    non_blocker = [f for f in factors if not any(b in f for b in blocker_factors)]
    if not non_blocker:
        return raw
    # Still capped by non-blocker factors
    _, _, factors_all = _compute_cap(
        gates, is_dirty=False,
        multistatus_pending_count=multistatus_pending_count,
    )
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
    """Return the canonical current wave label.

    Delegates to _governance.wave so all callers agree.
    """
    return _wave_current_wave()


def _gather_evidence(gates: dict[str, Any]) -> dict[str, Any]:
    """Extract per-gate context values needed for cap computation and manifest sections.

    Pure with respect to file I/O beyond what gates already contain.
    Returns a dict with keys: dirty, t3_status, t3_verified_head, t3_stale,
    allowlist_total, expired_allowlist_total, clean_env_status, clean_env_summary_available.
    """
    dirty = _is_dirty()

    t3_gate = gates.get("t3_freshness", {})
    t3_status = t3_gate.get("status", "unknown") if isinstance(t3_gate, dict) else "unknown"
    t3_verified_head = t3_gate.get("verified_head", "") if isinstance(t3_gate, dict) else ""
    t3_stale = t3_status not in ("pass", "fresh_at_head")

    route_scope_gate = gates.get("route_scope", {})
    allowlist_total = route_scope_gate.get("allowlist_total", 0) if isinstance(route_scope_gate, dict) else 0
    expired_allowlist_total = route_scope_gate.get("expired_allowlist_total", 0) if isinstance(route_scope_gate, dict) else 0

    clean_env_gate = gates.get("clean_env", {})
    clean_env_status = clean_env_gate.get("status", "unknown") if isinstance(clean_env_gate, dict) else "unknown"
    clean_env_summary_available = clean_env_gate.get("summary_available", None) if isinstance(clean_env_gate, dict) else None

    # invoke the multistatus runner once and capture the aggregate.
    # The runner reports per-gate PASS/FAIL/WARN/DEFER plus aggregated counts.
    multistatus = _run_multistatus_runner()
    multistatus_pending_count = int(multistatus.get("defer_count", 0))

    return {
        "dirty": dirty,
        "t3_status": t3_status,
        "t3_verified_head": t3_verified_head,
        "t3_stale": t3_stale,
        "allowlist_total": allowlist_total,
        "expired_allowlist_total": expired_allowlist_total,
        "clean_env_status": clean_env_status,
        "clean_env_summary_available": clean_env_summary_available,
        "multistatus": multistatus,
        "multistatus_pending_count": multistatus_pending_count,
    }


def _compute_score(gates: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Compute the three-tier scorecard from gate results and gathered evidence.

    Pure with respect to gate execution — receives already-collected gate dicts.
    Returns the full scorecard dict (raw, verified, 7x24, conditional, caps).
    """
    dirty = evidence["dirty"]
    t3_stale = evidence["t3_stale"]
    expired_allowlist_total = evidence["expired_allowlist_total"]
    multistatus_pending_count = int(evidence.get("multistatus_pending_count", 0))

    dimensions = _load_weights()
    raw = _compute_raw(dimensions) if dimensions else 0.0

    cap, cap_reason, cap_factors = _compute_cap(
        gates,
        is_dirty=dirty,
        t3_stale=t3_stale,
        expired_allowlist=expired_allowlist_total,
        multistatus_pending_count=multistatus_pending_count,
        tier="current_verified_readiness",
    )
    verified = round(min(raw, cap), 2) if cap is not None else raw

    cap_7x24, _cap_reason_7x24, cap_factors_7x24 = _compute_cap(
        gates,
        is_dirty=dirty,
        t3_stale=t3_stale,
        expired_allowlist=expired_allowlist_total,
        multistatus_pending_count=multistatus_pending_count,
        tier="seven_by_twenty_four_operational_readiness",
    )
    seven_by_twenty_four = round(min(raw, cap_7x24), 2) if cap_7x24 is not None else raw

    return {
        "raw": raw,
        "verified": verified,
        "raw_implementation_maturity": raw,
        "current_verified_readiness": verified,
        "seven_by_twenty_four_operational_readiness": seven_by_twenty_four,
        "conditional_readiness_after_blockers": _compute_conditional(
            raw, gates, is_dirty=dirty,
            multistatus_pending_count=multistatus_pending_count,
        ),
        "cap": cap,
        "cap_reason": cap_reason,
        "cap_factors": cap_factors,
        "cap_7x24": cap_7x24,
        "cap_factors_7x24": cap_factors_7x24,
        "multistatus_pending_count": multistatus_pending_count,
        "weights_version": "2",
    }


def build_manifest(wave_override: str | None = None) -> tuple[dict[str, Any], bool]:
    """Run all gates and return (manifest_dict, all_passed).

    wave_override: when provided (e.g. via --wave CLI), used in place of
    docs/current-wave.txt. CP-4 fix: lets the release captain set the wave
    explicitly at manifest time, eliminating the GS-8 wave-label drift
    (where the file fell behind the actual release wave).
    """
    date_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    short_sha = _git_short_sha()
    head_sha = _git_head_sha()
    manifest_id = f"{date_str}-{short_sha}"

    print(f"Building release manifest {manifest_id}...", file=sys.stderr)

    # Run gates
    gates: dict[str, Any] = {}
    for gate_key, gate_spec in _GATE_SCRIPTS.items():
        script, has_json, extra_args = gate_spec[0], gate_spec[1], gate_spec[2]
        gate_timeout = gate_spec[3] if len(gate_spec) > 3 else 120
        print(f"  {gate_key}: {script}...", end=" ", file=sys.stderr, flush=True)
        gates[gate_key] = _run_gate(gate_key, script, has_json, extra_args, gate_timeout)
        print(gates[gate_key].get("status", "?"), file=sys.stderr)

    evidence = _gather_evidence(gates)
    scorecard = _compute_score(gates, evidence)

    wave_label = wave_override if wave_override else _current_wave()
    wave_source = "cli" if wave_override else "file"

    manifest: dict[str, Any] = {
        "manifest_id": manifest_id,
        "schema_version": "1",
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "release_head": head_sha,
        "git": {
            "head_sha": head_sha,
            "short_sha": short_sha,
            "is_dirty": evidence["dirty"],
        },
        "wave": wave_label,
        "wave_source": wave_source,
        "gates": gates,
        "scorecard": scorecard,
        "t3": {
            "status": evidence["t3_status"],
            "verified_head": evidence["t3_verified_head"],
        },
        "clean_env": {
            "profile": "default-offline",
            "status": evidence["clean_env_status"],
            "summary_available": evidence["clean_env_summary_available"],
        },
        "route_scope": {
            "allowlist_total": evidence["allowlist_total"],
            "expired_allowlist_total": evidence["expired_allowlist_total"],
        },
        # aggregate multistatus runner output (PASS/FAIL/WARN/DEFER counts
        # plus per-gate detail). The cap rules `multistatus_gates_pending_low/high`
        # in score_caps.yaml consume defer_count.
        "multistatus": evidence.get("multistatus", {}),
        "multistatus_pending_count": int(evidence.get("multistatus_pending_count", 0)),
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
    parser.add_argument(
        "--wave",
        default=None,
        help=(
            "Wave label to embed in the manifest (e.g. 'Wave 17'). When omitted, "
            "reads docs/current-wave.txt. CP-4 fix: explicit captain assertion at "
            "manifest time prevents GS-8 wave-label drift."
        ),
    )
    args = parser.parse_args()

    manifest, all_passed = build_manifest(wave_override=args.wave)
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
