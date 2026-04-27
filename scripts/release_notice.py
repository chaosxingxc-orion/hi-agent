#!/usr/bin/env python3
"""Atomic release notice generator.

Usage: python scripts/release_notice.py --wave 10.6 [--allow-dirty] [--dry-run]

Steps:
  1. Refuse if `git status --porcelain` has uncommitted changes, unless --allow-dirty
  2. Resolve HEAD via `git rev-parse HEAD` (short 7-char)
  3. Read template from docs/downstream-responses/_templates/notice-{wave}.md
  4. Substitute {{HEAD}}, {{DATE}}, {{WAVE}}, {{SCORE_CAP}} placeholders
  5. Write to docs/downstream-responses/{date}-wave{wave}-delivery-notice.md
  6. git add the notice file
  7. git commit with message: "docs(GOV): Wave {wave} delivery notice [release_notice.py]"
  8. Re-resolve HEAD (it may have changed due to commit)
  9. Re-read the generated notice, check that Functional HEAD field matches new HEAD
  10. If mismatch: rewrite notice with updated HEAD, git add, git commit --amend, re-check
  11. Cap reflection loop at 2 iterations
  12. Print final HEAD and notice path
"""
from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = ROOT / "docs" / "downstream-responses" / "_templates"
NOTICES_DIR = ROOT / "docs" / "downstream-responses"

_DEFAULT_T3_EVIDENCE = "PENDING — run scripts/run_t3_gate.py"
_DEFAULT_CLEAN_ENV_EVIDENCE = "PENDING — run verify_clean_env.py --profile default-offline"


def _format_score_cap(manifest_dict: dict | None = None) -> str:
    """Derive score cap description from manifest or score_caps.yaml.

    Never returns a hardcoded literal — always reads from the registry.
    """
    if manifest_dict:
        sc = manifest_dict.get("scorecard", {})
        cap = sc.get("cap")
        reason = sc.get("cap_reason", "")
        if cap is not None:
            return f"{cap:.1f} ({reason})"
    # Fall back to reading score_caps.yaml directly
    caps_file = ROOT / "docs" / "governance" / "score_caps.yaml"
    if caps_file.exists():
        import re as _re
        text = caps_file.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("- condition: t3_deferred"):
                # Find next cap: line
                pass
            m = _re.match(r"^\s+cap:\s*(\d+(?:\.\d+)?)", line)
            if m:
                return f"{float(m.group(1)):.1f} (see docs/governance/score_caps.yaml for cap rules)"
    return "see docs/governance/score_caps.yaml"


def _git_run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=check,
    )


def _git_head_short() -> str:
    """Return the current HEAD SHA as a 7-char short hash."""
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git rev-parse --short HEAD failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_status_porcelain() -> str:
    """Return raw output of git status --porcelain."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git status failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _render_template(template_text: str, wave: str, head: str, date: str) -> str:
    """Substitute all placeholders in the template."""
    text = template_text
    text = text.replace("{{HEAD}}", head)
    text = text.replace("{{DATE}}", date)
    text = text.replace("{{WAVE}}", wave)
    text = text.replace("{{SCORE_CAP}}", _format_score_cap())
    text = text.replace("{{T3_EVIDENCE}}", _DEFAULT_T3_EVIDENCE)
    text = text.replace("{{CLEAN_ENV_EVIDENCE}}", _DEFAULT_CLEAN_ENV_EVIDENCE)
    return text


def _extract_functional_head(notice_text: str) -> str | None:
    """Extract the Functional HEAD SHA from a rendered notice."""
    import re

    for line in notice_text.splitlines():
        m = re.search(r"Functional HEAD:\s*([0-9a-f]{7,40})", line, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _update_head_in_notice(notice_text: str, old_head: str, new_head: str) -> str:
    """Replace all occurrences of old_head with new_head in notice text."""
    return notice_text.replace(old_head, new_head)


def _notice_filename(wave: str, date: str) -> str:
    """Return the canonical notice filename."""
    # Sanitize wave for use in filename (replace '.' with '-' for safe filename)
    wave_safe = wave.replace(".", "-")
    return f"{date}-wave{wave_safe}-delivery-notice.md"


def _git_add(path: Path) -> None:
    """Stage a file."""
    result = subprocess.run(
        ["git", "add", str(path)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git add failed: {result.stderr.strip()}")


def _git_commit(message: str) -> None:
    """Create a new commit."""
    result = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git commit failed: {result.stderr.strip()}")


def _git_commit_amend() -> None:
    """Amend the last commit without changing its message."""
    result = subprocess.run(
        ["git", "commit", "--amend", "--no-edit"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git commit --amend failed: {result.stderr.strip()}")


def run(wave: str, allow_dirty: bool = False, dry_run: bool = False) -> int:
    """Execute the atomic release notice workflow.

    Returns 0 on success, non-zero on failure.
    """
    # Step 1: dirty-tree guard
    porcelain = _git_status_porcelain()
    if porcelain and not allow_dirty:
        print(
            "ERROR: Working tree has uncommitted changes. Commit or stash them first,\n"
            "or pass --allow-dirty to bypass this check.\n"
            f"Dirty files:\n{porcelain}",
            file=sys.stderr,
        )
        return 1

    # Step 2: resolve HEAD
    head = _git_head_short()
    date = datetime.date.today().isoformat()

    # Step 3: read template
    template_path = TEMPLATES_DIR / f"notice-{wave}.md"
    if not template_path.exists():
        print(
            f"ERROR: Template not found: {template_path}\n"
            f"Expected: docs/downstream-responses/_templates/notice-{wave}.md",
            file=sys.stderr,
        )
        return 1
    template_text = template_path.read_text(encoding="utf-8")

    # Step 4: substitute placeholders
    notice_text = _render_template(template_text, wave=wave, head=head, date=date)

    # Step 5: determine output path
    filename = _notice_filename(wave, date)
    notice_path = NOTICES_DIR / filename

    if dry_run:
        print(f"[dry-run] Would write notice to: {notice_path}")
        print(f"[dry-run] HEAD at render time: {head}")
        print(f"[dry-run] Template: {template_path}")
        print("\n--- Rendered notice (first 40 lines) ---")
        for line in notice_text.splitlines()[:40]:
            print(line)
        print("--- end ---")
        return 0

    # Step 5 (actual): write notice
    notice_path.write_text(notice_text, encoding="utf-8")
    print(f"Written: {notice_path}")

    # Step 6: git add
    _git_add(notice_path)

    # Step 7: git commit
    commit_msg = f"docs(GOV): Wave {wave} delivery notice [release_notice.py]"
    _git_commit(commit_msg)
    print(f"Committed: {commit_msg}")

    # Steps 8-11: post-commit HEAD realignment loop (cap at 2 iterations)
    for iteration in range(1, 3):
        # Step 8: re-resolve HEAD after commit
        new_head = _git_head_short()

        # Step 9: check Functional HEAD in notice matches new HEAD
        current_text = notice_path.read_text(encoding="utf-8")
        declared_head = _extract_functional_head(current_text)

        if declared_head is None:
            print(
                f"WARNING: Could not find 'Functional HEAD:' in notice after iteration {iteration}."
            )
            break

        if declared_head == new_head or new_head.startswith(declared_head):
            # Aligned: done
            break

        # Step 10: mismatch — rewrite notice with new HEAD
        print(
            f"[iteration {iteration}] HEAD mismatch: notice declares {declared_head}, "
            f"actual is {new_head}. Realigning..."
        )
        updated_text = _update_head_in_notice(current_text, declared_head, new_head)
        notice_path.write_text(updated_text, encoding="utf-8")
        _git_add(notice_path)
        _git_commit_amend()
        print(f"[iteration {iteration}] Amended commit with updated HEAD {new_head}")

    # Step 12: print final result
    final_head = _git_head_short()
    print("\nDone.")
    print(f"  Final HEAD:   {final_head}")
    print(f"  Notice path:  {notice_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Atomically generate, commit, and verify a delivery notice."
    )
    parser.add_argument(
        "--wave",
        required=True,
        help="Wave identifier, e.g. '10.6'",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        default=False,
        help="Skip the dirty-tree guard (use with caution).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Render the notice and print what would happen, but do not commit.",
    )
    args = parser.parse_args()
    return run(wave=args.wave, allow_dirty=args.allow_dirty, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
