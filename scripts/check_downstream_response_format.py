#!/usr/bin/env python3
"""Optional: only run if you produce downstream response notices for the research-intelligence team.

Validates that delivery notices produced for the research-intelligence team follow
their expected format — including 'Validated by:' headers and score-cap rules.

This script is NOT called by the platform CI (check_doc_consistency.py).
It is provided for the research-intelligence team to run locally if they want
to validate their own notice format.

Usage:
    python scripts/check_downstream_response_format.py [notice-file]

If no notice-file is given, the most-recently-modified delivery notice under
docs/downstream-responses/ is used.
"""
from __future__ import annotations

import contextlib
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"


def _git_head(repo_root: Path = ROOT) -> str | None:
    """Return the current HEAD SHA, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return None


def _t3_is_fresh(repo_root: Path = ROOT) -> bool:
    """Return True when T3 evidence covers current HEAD (no hot-path changes since gate)."""
    try:
        delivery_dir = repo_root / "docs" / "delivery"
        if not delivery_dir.is_dir():
            return False
        candidates = sorted(
            delivery_dir.glob("*-rule15-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return False
        latest = candidates[0]

        gate_sha: str | None = None
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            gate_sha = data.get("sha") if isinstance(data.get("sha"), str) else None
        except (json.JSONDecodeError, OSError):
            pass
        if not gate_sha:
            m = re.search(r"-([0-9a-f]{7,40})-rule15", latest.name)
            gate_sha = m.group(1) if m else None
        if not gate_sha:
            return False

        head = _git_head(repo_root)
        if not head:
            return False
        if head.startswith(gate_sha) or gate_sha.startswith(head[: len(gate_sha)]):
            return True

        result = subprocess.run(
            ["git", "diff", "--name-only", f"{gate_sha}..HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if result.returncode != 0:
            return False
        hot_patterns = [
            "hi_agent/llm/**",
            "hi_agent/runtime/**",
            "hi_agent/config/cognition_builder.py",
            "hi_agent/config/json_config_loader.py",
            "hi_agent/config/builder.py",
            "hi_agent/runner.py",
            "hi_agent/runner_stage.py",
            "hi_agent/runtime_adapter/**",
            "hi_agent/memory/compressor.py",
            "hi_agent/server/app.py",
            "hi_agent/profiles/**",
        ]
        changed = [f for f in result.stdout.splitlines() if f.strip()]
        for f in changed:
            for pat in hot_patterns:
                if fnmatch.fnmatch(f, pat) or fnmatch.fnmatch(f.replace("\\", "/"), pat):
                    return False
        return True
    except Exception:
        return False


def check_score_cap(notice: Path | None = None) -> list[str]:
    """Declared readiness score must not exceed the cap for the T3 status.

    Cap rules:
    - T3 stale: max 76.5
    - T3 fresh but no clean-env evidence JSON for current HEAD: max 78.0
    - T3 fresh + clean-env evidence present + HEAD aligned: no cap

    Extended check: if score > 76.5 and no 'Validated by:' field present,
    emit a WARNING (not hard FAIL) about missing validation record.
    """
    errors: list[str] = []
    if notice is None:
        notices = sorted(DOCS.glob("downstream-responses/2026-*-delivery-notice.md"), reverse=True)
        if not notices:
            return errors
        notice = notices[0]

    src = notice.read_text(encoding="utf-8", errors="replace")

    score: float | None = None
    for line in src.splitlines():
        m = re.search(r"Current verified readiness:\s*([\d.]+)", line)
        if m:
            with contextlib.suppress(ValueError):
                score = float(m.group(1))
            break
    if score is None:
        return errors

    t3_fresh = _t3_is_fresh(ROOT)

    head = _git_head(ROOT)
    has_clean_env_evidence = False
    if head and t3_fresh:
        delivery_dir = DOCS / "delivery"
        if delivery_dir.is_dir():
            for f in delivery_dir.glob("*.json"):
                if head[:7] in f.name:
                    has_clean_env_evidence = True
                    break

    if not t3_fresh:
        cap = 76.5
        status = "stale"
    elif not has_clean_env_evidence:
        cap = 78.0
        status = "fresh-no-clean-env"
    else:
        cap = None
        status = "uncapped"

    if cap is not None and score > cap:
        try:
            rel = notice.relative_to(DOCS.parent)
        except ValueError:
            rel = notice
        errors.append(
            f"  SCORE-CAP-VIOLATION: {rel} declares "
            f"{score}, max allowed {cap} (T3: {status})"
        )

    # Warn when score > 76.5 but Validated by: is absent
    if score > 76.5:
        has_validated_by = bool(re.search(r"Validated by:\s*\S", src, re.IGNORECASE))
        if not has_validated_by:
            try:
                rel = notice.relative_to(DOCS.parent)
            except ValueError:
                rel = notice
            errors.append(
                f"  WARNING MISSING-VALIDATED-BY: {rel} declares readiness {score} > 76.5 "
                "but has no 'Validated by:' field. Add 'Validated by: <scripts>' to the "
                "notice header block (generated automatically by release_notice.py)."
            )

    return errors


def check_validated_by_header() -> list[str]:
    """Wave notices with score > 76.5 must carry a 'Validated by:' field.

    Scans all wave notices in docs/downstream-responses/ for a ``Validated by:``
    field inside the code block at the top of the notice.  If the notice's
    declared ``Current verified readiness:`` exceeds 76.5 but ``Validated by:``
    is missing or empty, emits a WARNING (not a hard FAIL).

    Draft notices (``Status: draft``) are exempt.
    """
    warnings: list[str] = []
    for notice in DOCS.glob("downstream-responses/2026-*-wave*-notice.md"):
        src = notice.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        # Skip draft notices
        if any(re.search(r"Status:.*(?:draft|superseded)", line, re.IGNORECASE) for line in lines):
            continue

        score: float | None = None
        for line in lines:
            m = re.search(r"Current verified readiness:\s*([\d.]+)", line)
            if m:
                with contextlib.suppress(ValueError):
                    score = float(m.group(1))
                break

        if score is None or score <= 76.5:
            continue

        has_validated_by = bool(re.search(r"Validated by:\s*\S", src, re.IGNORECASE))
        if not has_validated_by:
            try:
                rel = notice.relative_to(DOCS.parent)
            except ValueError:
                rel = notice
            warnings.append(
                f"  WARNING MISSING-VALIDATED-BY: {rel} declares readiness {score} > 76.5 "
                "but has no 'Validated by:' field in the notice header block. "
                "Regenerate with scripts/release_notice.py to add this field."
            )

    return warnings


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    notice: Path | None = None
    if args:
        notice = Path(args[0])
        if not notice.exists():
            print(f"FAIL check_downstream_response_format: file not found: {notice}")
            return 1

    all_errors: list[str] = []
    all_errors.extend(check_score_cap(notice))
    all_errors.extend(check_validated_by_header())

    if all_errors:
        print("FAIL check_downstream_response_format:")
        for e in all_errors:
            print(e)
        return 1
    print("OK check_downstream_response_format")
    return 0


if __name__ == "__main__":
    sys.exit(main())
