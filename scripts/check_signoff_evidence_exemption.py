#!/usr/bin/env python3
"""W35-corrective §5.2: signoff evidence-exemption discipline.

Per RIA W35 corrective directive §5.2: when a wave signoff cites evidence
files whose head differs from the release_head, the signoff MUST carry an
explicit ``evidence_exemption`` clause naming:

  - ``kind`` (gov_infra_gap | docs_only_gap | rerun_pending | none)
  - ``evidence_head``, ``release_head`` (the divergent SHAs)
  - ``rationale`` (a non-empty string)
  - ``hot_path_audit`` (a non-empty string)
  - one of: ``commits_in_gap`` (list, gov_infra path) OR a future-cycle
    ``next_action`` field naming when re-run evidence will be collected.

The cap rule ``clean_env_not_final_head`` (cap=60) covers the hard case
(no exemption + non-gov-infra gap). This gate covers the soft case the
cap rule does not see: an exemption that is missing fields or that cites
a gap kind that does not match the actual gov-infra-only-ness of the
commit range.

Exit 0 (pass): signoff has no divergence OR exemption is well-formed.
Exit 1 (fail): divergence exists and exemption is missing or malformed.
Exit 2 (deferred): no W{current_wave}-signoff.json found.

Invocation: ``python scripts/check_signoff_evidence_exemption.py [--json]``.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _governance.governance_gap import is_gov_only_gap
from _governance.wave import current_wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"

REQUIRED_EXEMPTION_FIELDS: tuple[str, ...] = (
    "kind",
    "evidence_head",
    "release_head",
    "rationale",
    "hot_path_audit",
)

VALID_EXEMPTION_KINDS: frozenset[str] = frozenset(
    {"gov_infra_gap", "docs_only_gap", "rerun_pending", "none"}
)


def _signoff_path(wave: int) -> pathlib.Path | None:
    candidate = RELEASES_DIR / f"wave{wave}-signoff.json"
    return candidate if candidate.exists() else None


def _shorten(sha: str, n: int = 12) -> str:
    return sha[:n] if sha else ""


def _heads_match(a: str, b: str) -> bool:
    """SHA equality at the shortest common prefix (>=8 chars)."""
    if not a or not b:
        return False
    n = min(len(a), len(b), 12)
    if n < 8:
        return False
    return a[:n] == b[:n]


def _extract_evidence_heads(signoff: dict) -> dict[str, str]:
    """Pull evidence head SHAs out of evidence path strings.

    Each evidence path is conventionally ``docs/{verification,delivery}/<HEAD>-...``
    or ``docs/delivery/<DATE>-<HEAD>-t3-volces.json``. We extract the first
    SHA-shaped token from each filename.
    """
    evidence = signoff.get("evidence", {})
    out: dict[str, str] = {}
    sha_re = re.compile(r"\b([0-9a-f]{7,40})\b")
    for key in ("default_offline_clean_env", "arch_7x24", "t3_real_volces"):
        path = str(evidence.get(key, ""))
        if not path:
            continue
        name = pathlib.Path(path).name
        match = sha_re.search(name)
        if match:
            out[key] = match.group(1)
    return out


def _audit_signoff(signoff: dict) -> tuple[bool, list[str]]:
    """Return (pass, violations).

    pass=True when there is no head divergence OR the exemption is well-formed.
    """
    violations: list[str] = []
    release_head = str(signoff.get("release_head", "")).strip()
    if not release_head:
        violations.append("release_head field missing or empty")
        return False, violations

    evidence_heads = _extract_evidence_heads(signoff)
    if not evidence_heads:
        return True, []

    diverged: list[tuple[str, str]] = [
        (key, head)
        for key, head in evidence_heads.items()
        if not _heads_match(head, release_head)
    ]
    if not diverged:
        return True, []

    exemption = signoff.get("evidence_exemption")
    if exemption is None:
        violations.append(
            "evidence diverges from release_head but no evidence_exemption "
            f"clause is present; diverged_heads={diverged} "
            f"release_head={_shorten(release_head)}"
        )
        return False, violations

    if not isinstance(exemption, dict):
        violations.append("evidence_exemption is not a JSON object")
        return False, violations

    for field in REQUIRED_EXEMPTION_FIELDS:
        value = exemption.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            violations.append(
                f"evidence_exemption.{field} is missing or empty"
            )

    kind = str(exemption.get("kind", "")).strip()
    if kind not in VALID_EXEMPTION_KINDS:
        violations.append(
            f"evidence_exemption.kind={kind!r} not in {sorted(VALID_EXEMPTION_KINDS)}"
        )

    if kind == "gov_infra_gap":
        commits = exemption.get("commits_in_gap")
        if commits is None or (isinstance(commits, list) and not commits):
            violations.append(
                "evidence_exemption.kind=gov_infra_gap requires non-empty "
                "commits_in_gap list"
            )
        # Verify the gap classification matches reality.
        evidence_head = str(exemption.get("evidence_head", "")).strip()
        if evidence_head and release_head:
            try:
                actual_gov_only = is_gov_only_gap(
                    evidence_head, release_head, repo_root=ROOT
                )
            except Exception as exc:
                actual_gov_only = None
                violations.append(
                    f"is_gov_only_gap raised on {evidence_head}..{release_head}: {exc}"
                )
            if actual_gov_only is False:
                violations.append(
                    f"evidence_exemption.kind=gov_infra_gap but git diff "
                    f"{_shorten(evidence_head)}..{_shorten(release_head)} "
                    "shows non-gov-infra changes (functional code modified)"
                )

    if kind == "rerun_pending":
        next_action = str(exemption.get("next_action", "")).strip()
        if not next_action:
            violations.append(
                "evidence_exemption.kind=rerun_pending requires non-empty "
                "next_action field naming when re-run will land"
            )

    return len(violations) == 0, violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Signoff evidence-exemption discipline gate."
    )
    parser.add_argument("--json", action="store_true", help="emit JSON result")
    args = parser.parse_args(argv)

    try:
        wave = current_wave()
    except Exception as exc:
        result = {
            "check": "signoff_evidence_exemption",
            "status": "deferred",
            "reason": f"current_wave() failed: {exc}",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"DEFERRED: {result['reason']}", file=sys.stderr)
        return 2

    signoff_file = _signoff_path(wave)
    if signoff_file is None:
        result = {
            "check": "signoff_evidence_exemption",
            "status": "deferred",
            "reason": f"no signoff file at docs/releases/wave{wave}-signoff.json",
            "wave": wave,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"DEFERRED: {result['reason']}")
        return 2

    try:
        signoff = json.loads(signoff_file.read_text(encoding="utf-8"))
    except Exception as exc:
        result = {
            "check": "signoff_evidence_exemption",
            "status": "fail",
            "violations": [f"signoff JSON unreadable: {exc}"],
            "signoff": str(signoff_file),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"FAIL signoff_evidence_exemption: {result['violations'][0]}", file=sys.stderr)
        return 1

    passed, violations = _audit_signoff(signoff)
    status = "pass" if passed else "fail"
    result = {
        "check": "signoff_evidence_exemption",
        "status": status,
        "signoff": str(signoff_file.relative_to(ROOT)),
        "wave": wave,
        "violations": violations,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if passed:
            print(f"PASS signoff_evidence_exemption (wave={wave})")
        else:
            for v in violations:
                print(f"FAIL signoff_evidence_exemption: {v}", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
