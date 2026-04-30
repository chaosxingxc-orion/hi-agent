#!/usr/bin/env python
"""Rule 8 T3 Invariance freshness check (DF-46).

Exit 0: T3 evidence covers HEAD (no hot-path changes since last gate recording).
Exit 1: T3 stale — hot-path file(s) changed since the last gate SHA.

Usage::

    python scripts/check_t3_freshness.py

The script:
1. Finds the most recent ``docs/delivery/*-rule15-*.json`` or
   ``docs/delivery/*-t3-*.json`` file.
2. Extracts the gate SHA from the JSON ``verified_head`` field (preferred), or
   the legacy ``sha`` field, or falls back to parsing the filename
   (e.g. ``2026-04-24-8c5395b-rule15-volces.json`` → ``8c5395b``).
3. Lists files changed between <gate_sha>..HEAD via ``git diff --name-only``.
4. Checks those paths against the hot-path glob list from CLAUDE.md Rule 8.
5. Exits 1 if any hot-path file changed; exits 0 otherwise.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._governance.hot_paths import HOT_PATH_PATTERNS as _HOT_PATH_PATTERNS


def _is_hot_path(file_path: str) -> bool:
    """Return True if *file_path* matches any hot-path glob pattern."""
    for pattern in _HOT_PATH_PATTERNS:
        if fnmatch.fnmatch(file_path, pattern):
            return True
        # Also match with forward-slash normalization
        normalized = file_path.replace("\\", "/")
        if fnmatch.fnmatch(normalized, pattern):
            return True
    return False


def _find_latest_delivery_file(repo_root: Path) -> Path | None:
    """Return the most recently modified T3 delivery JSON file.

    Accepts both the legacy ``*-rule15-*.json`` pattern and the modern
    ``*-t3-*.json`` pattern introduced alongside the ``verified_head`` field.

    In CI all files share the same checkout mtime, so filename is used as a
    secondary sort key (descending) — YYYY-MM-DD prefixes ensure the most
    recently dated file wins among equal-mtime candidates.
    """
    delivery_dir = repo_root / "docs" / "delivery"
    if not delivery_dir.is_dir():
        return None
    candidates = [
        p for p in (
            list(delivery_dir.glob("*-rule15-*.json")) +
            list(delivery_dir.glob("*-t3-*.json"))
        )
        # Exclude provenance sidecar files (end with -provenance.json);
        # they are paired metadata, not T3 evidence artifacts.
        if not p.name.endswith("-provenance.json")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return candidates[0]


def _extract_sha_from_json(delivery_file: Path) -> str | None:
    """Try to read the ``sha`` field from the delivery JSON."""
    try:
        data = json.loads(delivery_file.read_text(encoding="utf-8"))
        sha = data.get("sha")
        if sha and isinstance(sha, str) and len(sha) >= 7:
            return sha
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _extract_sha_from_filename(delivery_file: Path) -> str | None:
    """Fall back: parse a 7-char hex SHA from the filename stem.

    Filename conventions supported:
    - Legacy: ``YYYY-MM-DD-<sha7>-rule15-<tag>.json``
    - Modern: ``YYYY-MM-DD-<sha7>-t3-<provider>.json``
    """
    match = re.search(r"-([0-9a-f]{7,40})-(?:rule15|t3)-", delivery_file.name)
    if match:
        return match.group(1)
    return None


def _extract_sha_from_evidence(evidence_path: Path, evidence_data: dict) -> str:
    """Extract gate SHA: prefer ``verified_head`` field, then legacy ``sha`` field,
    then fall back to filename parsing.

    Returns an empty string when no SHA can be determined.
    """
    # 1. Prefer the canonical verified_head field (modern files).
    verified_head = evidence_data.get("verified_head")
    if verified_head and isinstance(verified_head, str) and len(verified_head) >= 7:
        return verified_head

    # 2. Legacy: sha field written by older gate scripts.
    sha = evidence_data.get("sha")
    if sha and isinstance(sha, str) and len(sha) >= 7:
        return sha

    # 3. Final fallback: parse from filename.
    return _extract_sha_from_filename(evidence_path) or ""


def _git(args: list[str], *, repo_root: Path) -> str:
    """Run a git command and return stdout, stripping trailing whitespace."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {result.returncode}):\n{result.stderr}"
        )
    return result.stdout.strip()


def _check_clean_env_evidence(repo_root: Path, head_sha: str) -> None:
    """Print STATUS: T3-FRESH-AND-CLEAN-ENV-VERIFIED or STATUS: T3-FRESH (...).

    Looks for docs/delivery/*<head_sha>*clean-env*.json (short or full SHA)
    with bundle_profile in {"default-offline", "release"} and status == "passed".
    Called only after T3 is confirmed fresh.
    """
    import json as _json

    delivery_dir = repo_root / "docs" / "delivery"
    if not delivery_dir.is_dir():
        print("STATUS: T3-FRESH (clean-env not verified at current HEAD)")
        return

    short_sha = head_sha[:7]
    # Collect candidate files matching short or full SHA
    candidates: list[Path] = []
    for pattern in (
        f"*{short_sha}*clean-env*.json",
        f"*{head_sha}*clean-env*.json",
    ):
        candidates.extend(delivery_dir.glob(pattern))

    clean_env_verified = False
    verified_file: str = ""
    for ce_path in candidates:
        try:
            ce_data = _json.loads(ce_path.read_text(encoding="utf-8"))
            profile = ce_data.get("bundle_profile", "")
            ce_status = ce_data.get("status", "")
            if profile in {"default-offline", "release"} and ce_status == "passed":
                clean_env_verified = True
                verified_file = ce_path.name
                break
        except (_json.JSONDecodeError, OSError):
            pass

    if clean_env_verified:
        print(f"STATUS: T3-FRESH-AND-CLEAN-ENV-VERIFIED ({verified_file})")
    else:
        print("STATUS: T3-FRESH (clean-env not verified at current HEAD)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent

    # 1. Find latest delivery file.
    delivery_file = _find_latest_delivery_file(repo_root)
    if delivery_file is None:
        print(
            "T3-WARN: No docs/delivery/*-rule15-*.json or *-t3-*.json found. "
            "T3 gate has never been recorded — treating as stale.",
            file=sys.stderr,
        )
        if args.json_output:
            print(json.dumps({"check": "t3_freshness", "status": "fail",
                              "reason": "no delivery file found"}))
        return 1

    if not args.json_output:
        print(f"T3: Using delivery file: {delivery_file.name}")

    # 2. Extract gate SHA — load file data so _extract_sha_from_evidence can
    #    inspect both fields and filename in one call.
    try:
        delivery_data: dict = json.loads(delivery_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # Corrupted artifact is explicitly flagged — not silently skipped
        reason = f"corrupted delivery artifact {delivery_file.name}: {exc}"
        if args.json_output:
            print(json.dumps({
                "check": "t3_freshness",
                "status": "deferred",
                "delivery_file": delivery_file.name,
                "reason": reason,
                "provenance": "unknown",
            }))
        else:
            print(f"T3-WARN: {reason} — treating as provenance_unknown deferred", file=sys.stderr)
        return 0  # deferred, not fail — allows cap to apply

    # Reject structural provenance unless explicitly shape-verified
    provenance = delivery_data.get("provenance", "")
    if provenance in ("synthetic", "structural") and delivery_data.get("mode") != "shape_verified":
        gate_sha_prov = _extract_sha_from_evidence(delivery_file, delivery_data)
        if args.json_output:
            print(json.dumps({
                "check": "t3_freshness",
                "status": "deferred",
                "delivery_file": delivery_file.name,
                "verified_head": gate_sha_prov,
                "provenance": provenance,
                "reason": f"provenance:{provenance} rejected for T3 freshness — requires real or shape_verified",
            }))
        else:
            print(f"T3-WARN: {delivery_file.name} has provenance:{provenance} — not accepted as T3 evidence")
        return 0  # deferred with cap, not hard fail

    # If the delivery record explicitly marks this T3 as deferred, propagate that
    # status so the manifest builder can apply the t3_deferred cap (cap=72).
    delivery_status = delivery_data.get("status", "")
    if delivery_status == "deferred":
        gate_sha_for_deferred = _extract_sha_from_evidence(delivery_file, delivery_data)
        if args.json_output:
            print(json.dumps({
                "check": "t3_freshness",
                "status": "deferred",
                "delivery_file": delivery_file.name,
                "verified_head": gate_sha_for_deferred,
                "reason": delivery_data.get("reason", "T3 deferred per delivery record"),
                "deferred_to": delivery_data.get("deferred_to", ""),
            }))
        else:
            print(
                f"T3-DEFERRED: delivery record {delivery_file.name} declares "
                f"status=deferred. Cap factor t3_deferred will be applied."
            )
        return 0

    gate_sha = _extract_sha_from_evidence(delivery_file, delivery_data)
    if not gate_sha:
        print(
            f"T3-ERROR: Cannot determine gate SHA from {delivery_file.name}. "
            "Add a 'verified_head' field to the delivery JSON or use the naming convention "
            "YYYY-MM-DD-<sha7>-t3-<provider>.json (or legacy YYYY-MM-DD-<sha7>-rule15-<tag>.json).",
            file=sys.stderr,
        )
        if args.json_output:
            print(json.dumps({"check": "t3_freshness", "status": "fail",
                              "reason": "cannot determine gate SHA"}))
        return 1

    if not args.json_output:
        print(f"T3: Gate SHA = {gate_sha}")

    # 3. Get HEAD SHA.
    try:
        head_sha = _git(["rev-parse", "HEAD"], repo_root=repo_root)
    except RuntimeError as exc:
        print(f"T3-ERROR: {exc}", file=sys.stderr)
        if args.json_output:
            print(json.dumps({"check": "t3_freshness", "status": "fail",
                              "reason": str(exc)}))
        return 1

    if not args.json_output:
        print(f"T3: HEAD SHA  = {head_sha}")

    if head_sha.startswith(gate_sha) or gate_sha.startswith(head_sha[:len(gate_sha)]):
        if not args.json_output:
            print("T3: HEAD matches gate SHA — T3 is fresh.")
            _check_clean_env_evidence(repo_root, head_sha)
        else:
            print(json.dumps({"check": "t3_freshness", "status": "pass",
                              "verified_head": gate_sha, "reason": "HEAD matches gate SHA"}))
        return 0

    # 4. Get changed files between gate and HEAD.
    try:
        diff_output = _git(
            ["diff", "--name-only", f"{gate_sha}..HEAD"],
            repo_root=repo_root,
        )
    except RuntimeError as exc:
        print(
            f"T3-WARN: Could not compute diff from {gate_sha} to HEAD: {exc}\n"
            "Treating T3 as stale (gate SHA may not be reachable in this repo).",
            file=sys.stderr,
        )
        if args.json_output:
            print(json.dumps({"check": "t3_freshness", "status": "fail",
                              "reason": f"diff failed: {exc}"}))
        return 1

    changed_files = [f for f in diff_output.splitlines() if f.strip()]

    # 5. Filter hot-path files.
    hot_path_changes = [f for f in changed_files if _is_hot_path(f)]

    if not hot_path_changes:
        if not args.json_output:
            print(
                f"T3: {len(changed_files)} file(s) changed since gate; "
                "none are on the hot path. T3 is fresh."
            )
            _check_clean_env_evidence(repo_root, head_sha)
        else:
            print(json.dumps({
                "check": "t3_freshness", "status": "pass",
                "verified_head": gate_sha,
                "reason": f"{len(changed_files)} file(s) changed, none on hot path",
            }))
        return 0

    # 6. Exit 1 with structured output.
    print(
        f"T3-STALE: {len(hot_path_changes)} hot-path file(s) changed since gate "
        f"({gate_sha}):",
        file=sys.stderr,
    )
    for f in hot_path_changes:
        print(f"  {f}", file=sys.stderr)
    print(
        "\nRule 8 T3 Invariance violated. Record a fresh gate run before release:\n"
        "  python scripts/run_t3_gate.py --provider volces \\\n"
        "      --output docs/delivery/<date>-<sha7>-t3-volces.json\n"
        "Or tag this PR: T3 evidence: DEFERRED — <reason>",
        file=sys.stderr,
    )
    if args.json_output:
        print(json.dumps({
            "check": "t3_freshness", "status": "fail",
            "verified_head": gate_sha,
            "hot_path_changes": hot_path_changes,
            "reason": "hot-path files changed since gate",
        }))
    else:
        print("STATUS: STALE")
        print("CLEAN-ENV: NOT VERIFIED AT CURRENT HEAD")
    return 1


if __name__ == "__main__":
    sys.exit(main())
