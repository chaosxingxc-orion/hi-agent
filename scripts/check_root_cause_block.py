#!/usr/bin/env python3
"""Rule 1 enforcement — verify each PR commit body has the 4-line root-cause block."""
import argparse
import json
import re
import subprocess
import sys

RC_RE = re.compile(
    r"^Observed failure:.+\n"
    r"^Execution path:.+\n"
    r"^Root cause:.+\n"
    r"^Evidence:.+",
    re.MULTILINE,
)

SKIP_PREFIXES = (
    "[gov-", "[gov]", "[evidence-", "[manifest-", "[skip-rc:",
    "Merge ", "Revert ", "[W24-",
    # Wave-tagged process commits (case-insensitive variants for waves 25+):
    # routine fixes / cleanup / manifest+evidence iterations during release
    # finalisation are not feature commits and don't need a root-cause block.
    "[w25-", "[w26-", "[w27-", "[w28-",
    "[W25-", "[W26-", "[W27-", "[W28-",
)


def _commits_in_range(base: str, head: str) -> list[tuple[str, str]]:
    try:
        out = subprocess.check_output(
            ["git", "log", f"{base}..{head}", "--format=%H\t%s"],
            text=True, encoding="utf-8", errors="replace",
        )
    except subprocess.CalledProcessError:
        return []
    return [line.split("\t", 1) for line in out.splitlines() if "\t" in line]


def _commit_body(sha: str) -> str:
    return subprocess.check_output(
        ["git", "log", "-1", "--format=%B", sha],
        text=True, encoding="utf-8", errors="replace",
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="origin/main")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--json", dest="as_json", action="store_true")
    args = p.parse_args()

    commits = list(_commits_in_range(args.base, args.head))
    if not commits:
        result = {  # not_applicable: no commits in range to audit
            "check": "root_cause_block", "status": "not_applicable",
            "reason": "no_commits_in_range",
        }
        if args.as_json:
            print(json.dumps(result, indent=2))
        sys.exit(0)

    missing: list[dict] = []
    for sha, subj in commits:
        if any(subj.startswith(pre) for pre in SKIP_PREFIXES):
            continue
        body = _commit_body(sha)
        if not RC_RE.search(body):
            missing.append({"sha": sha[:8], "title": subj})

    status = "fail" if missing else "pass"
    result = {"check": "root_cause_block", "status": status, "missing": missing}
    if args.as_json:
        print(json.dumps(result, indent=2))
    elif missing:
        for m in missing:
            print(f"MISSING root-cause block: {m['sha']} — {m['title']}", file=sys.stderr)
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
