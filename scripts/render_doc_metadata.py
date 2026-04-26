"""Update ECC:LAST_UPDATED placeholders in docs from the latest release manifest.

Finds the most-recent manifest under docs/releases/, reads its manifest_id
and wave, and updates the date strings in:
  - README.md
  - docs/platform-capability-matrix.md

Also prints what changed; exits 1 if the latest manifest is not current HEAD.

Usage::

    python scripts/render_doc_metadata.py             # update in place
    python scripts/render_doc_metadata.py --check     # verify docs are up to date; exit 1 if stale
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MANIFEST_REF_RE = re.compile(r"Manifest:\s*\S+")


def _latest_manifest() -> dict | None:
    manifests = sorted(
        RELEASES_DIR.glob("platform-release-manifest-*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not manifests:
        return None
    try:
        data = json.loads(manifests[-1].read_text(encoding="utf-8"))
        data["_path"] = str(manifests[-1])
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _git_short_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(ROOT),
        ).stdout.strip()
    except Exception:
        return "unknown"


def _update_date_in_file(path: Path, new_date: str, manifest_id: str, check_only: bool) -> bool:
    """Update the first date line in the file. Returns True if a change was made/needed."""
    if not path.exists():
        print(f"SKIP {path.relative_to(ROOT)}: not found", file=sys.stderr)
        return False

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    changed = False

    for i, line in enumerate(lines):
        # Match lines like:  *最后更新：2026-04-25（Wave 9）*  or  Last updated: 2026-04-25 (...)
        if not _DATE_RE.search(line):
            continue
        if not re.search(r"(?:最后更新|Last updated|last updated)", line, re.IGNORECASE):
            continue

        new_line = _DATE_RE.sub(new_date, line, count=1)
        if new_line != line:
            print(
                f"  {path.relative_to(ROOT)}:{i+1}: {line.strip()!r} → {new_line.strip()!r}"
            )
            if not check_only:
                lines[i] = new_line
            changed = True
        break  # only update the first matching date line

    if changed and not check_only:
        path.write_text("".join(lines), encoding="utf-8")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Update ECC:LAST_UPDATED doc metadata.")
    parser.add_argument("--check", action="store_true",
                        help="Check mode: exit 1 if docs are stale, do not modify.")
    args = parser.parse_args()

    manifest = _latest_manifest()
    if manifest is None:
        print(
            "WARN: no release manifest found under docs/releases/; skipping update.",
            file=sys.stderr,
        )
        return 0

    manifest_id: str = manifest.get("manifest_id", "unknown")
    generated_at: str = manifest.get("generated_at", "")
    m = _DATE_RE.search(generated_at)
    new_date = m.group(0) if m else "unknown"

    head_sha = _git_short_head()
    manifest_sha = manifest.get("git", {}).get("short_sha", "")
    if manifest_sha and head_sha and not head_sha.startswith(manifest_sha[:len(head_sha)]):
        print(
            f"WARN: latest manifest is for {manifest_sha}, HEAD is {head_sha}. "
            "Run build_release_manifest.py first.",
            file=sys.stderr,
        )
        if args.check:
            return 1

    targets = [
        ROOT / "README.md",
        ROOT / "docs" / "platform-capability-matrix.md",
    ]

    any_stale = False
    for path in targets:
        stale = _update_date_in_file(path, new_date, manifest_id, check_only=args.check)
        if stale:
            any_stale = True

    if args.check and any_stale:
        print("FAIL: doc metadata is stale; run scripts/render_doc_metadata.py to update.")
        return 1

    if not any_stale:
        print("OK: doc metadata is current.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
