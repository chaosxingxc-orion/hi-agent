#!/usr/bin/env python3
"""CI gate: fail if latest release manifest is stale vs current HEAD.

Fails when:
- No manifest exists in docs/releases/
- manifest.release_head != git rev-parse HEAD
- manifest.git.is_dirty == true

Exit 0: manifest is current and clean.
Exit 1: manifest is stale, dirty, or missing.

Flags:
  --json  Emit structured JSON report.
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _latest_manifest() -> dict | None:
    # Sort by generated_at from inside each manifest JSON — this is stable across
    # CI runs where checkout mtime is the same for all files, and SHA-alphabetical
    # order is not chronological (e.g. bebc54a > 252500e but is an older manifest).
    import json as _json

    candidates = []
    for p in RELEASES_DIR.glob("platform-release-manifest-*.json"):
        try:
            data = _json.loads(p.read_text(encoding="utf-8"))
            generated_at = data.get("generated_at", "")
            candidates.append((generated_at, p.name, p, data))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    _, _, path, data = candidates[-1]
    data["_path"] = str(path)
    return data


def _manifest_commit_gap(manifest_head: str, current_head: str) -> bool:
    """Return True if commits between manifest_head..current_head only touch docs/releases/.

    Only called when --allow-docs-only-gap is passed; raises RuntimeError on subprocess error
    so the caller can treat gap detection failure as non-permissive.
    """
    if manifest_head == current_head:
        return True
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{manifest_head}..{current_head}"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        if result.returncode != 0:
            raise RuntimeError(f"git diff exited {result.returncode}: {result.stderr.strip()}")
        changed = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        _docs_prefixes = (
            "docs/releases/", "docs/verification/", "docs/delivery/",
            "docs/downstream-responses/", "docs/governance/", "docs/scorecard",
        )
        return all(any(f.startswith(p) for p in _docs_prefixes) for f in changed) and bool(changed)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"gap detection failed: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check release manifest freshness.")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument(
        "--allow-docs-only-gap",
        action="store_true",
        dest="allow_docs_only_gap",
        help=(
            "Opt-in: allow a HEAD mismatch when ALL changed files between manifest HEAD "
            "and current HEAD reside under docs/releases/. Default (without this flag) "
            "requires strict equality between manifest.release_head and current HEAD."
        ),
    )
    args = parser.parse_args(argv)

    head = _git_head()
    manifest = _latest_manifest()

    if manifest is None:
        msg = "no manifest found in docs/releases/"
        if args.json_output:
            report = {
                "check": "manifest_freshness",
                "status": "fail",
                "reason": msg,
                "head": head,
                "allow_docs_only_gap": args.allow_docs_only_gap,
            }
            print(json.dumps(report))
        else:
            print(f"FAIL manifest_freshness: {msg}")
        return 1

    manifest_head = manifest.get("release_head") or manifest.get("git", {}).get("head_sha", "")
    is_dirty = manifest.get("git", {}).get("is_dirty", True)

    reasons: list[str] = []
    head_mismatch = (
        head != "unknown"
        and manifest_head
        and not manifest_head.startswith(head)
        and not head.startswith(manifest_head[:len(head)])
    )
    if head_mismatch:
        # Always check for docs-only gap (Rule 14 permits release-commit gaps).
        # --allow-docs-only-gap retained for backward compat but no longer needed.
        try:
            gap_is_docs_only = _manifest_commit_gap(manifest_head, head)
        except RuntimeError as exc:
            reasons.append(f"gap_detection_failed: {exc}")
            gap_is_docs_only = False
        if not gap_is_docs_only:
            reasons.append(
                f"head_mismatch: manifest={manifest_head[:12]}, current={head[:12]}"
            )
    if is_dirty:
        reasons.append("manifest_was_dirty")

    if args.json_output:
        status = "fail" if reasons else "pass"
        print(json.dumps({
            "check": "manifest_freshness",
            "status": status,
            "manifest_head": manifest_head[:12] if manifest_head else "",
            "current_head": head[:12],
            "is_dirty": is_dirty,
            "reasons": reasons,
            "allow_docs_only_gap": args.allow_docs_only_gap,
        }, indent=2))
        return 1 if reasons else 0

    if reasons:
        print(f"FAIL manifest_freshness: {'; '.join(reasons)}")
        return 1

    print(f"OK manifest_freshness (manifest_head={manifest_head[:12]}, is_dirty=False)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

