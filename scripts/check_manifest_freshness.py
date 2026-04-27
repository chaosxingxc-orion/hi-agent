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
    manifests = sorted(
        RELEASES_DIR.glob("platform-release-manifest-*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not manifests:
        return None
    try:
        import json as _json
        data = _json.loads(manifests[-1].read_text(encoding="utf-8"))
        data["_path"] = str(manifests[-1])
        return data
    except Exception:
        return None


def _manifest_commit_gap(manifest_head: str, current_head: str) -> bool:
    """Return True if commits between manifest_head..current_head only touch docs/releases/."""
    if manifest_head == current_head:
        return True
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{manifest_head}..{current_head}"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        if result.returncode != 0:
            return False
        changed = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        return all(f.startswith("docs/releases/") for f in changed) and bool(changed)
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check release manifest freshness.")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    head = _git_head()
    manifest = _latest_manifest()

    if manifest is None:
        msg = "no manifest found in docs/releases/"
        if args.json_output:
            report = {"check": "manifest_freshness", "status": "fail", "reason": msg, "head": head}
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
        # Allow a single manifest-commit gap: if the only diff between manifest_head
        # and current HEAD touches only docs/releases/ (the manifest file itself),
        # the manifest is still considered current for the release gate.
        gap_is_manifest_only = _manifest_commit_gap(manifest_head, head)
        if not gap_is_manifest_only:
            reasons.append(f"head_mismatch: manifest={manifest_head[:12]}, current={head[:12]}")
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
        }, indent=2))
        return 1 if reasons else 0

    if reasons:
        print(f"FAIL manifest_freshness: {'; '.join(reasons)}")
        return 1

    print(f"OK manifest_freshness (manifest_head={manifest_head[:12]}, is_dirty=False)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
