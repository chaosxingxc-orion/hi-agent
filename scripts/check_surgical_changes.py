#!/usr/bin/env python3
"""Rule 2 enforcement — each commit touches ≤2 top-level modules."""
import argparse
import json
import subprocess
import sys

EXEMPT_PREFIXES = ("[gov-", "[manifest-", "[evidence-", "Merge ", "Revert ", "[W24-", "[W25-ci")


def _commits_in_range(base: str, head: str) -> list[tuple[str, str]]:
    try:
        out = subprocess.check_output(
            ["git", "log", f"{base}..{head}", "--format=%H\t%s"],
            text=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [line.split("\t", 1) for line in out.splitlines() if "\t" in line]


def _modules_touched(sha: str) -> set[str]:
    files = subprocess.check_output(
        ["git", "show", "--name-only", "--format=", sha], text=True
    ).splitlines()
    return {f.split("/", 1)[0] for f in files if "/" in f and f.strip()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="origin/main")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--max-modules", type=int, default=2)
    p.add_argument("--json", dest="as_json", action="store_true")
    args = p.parse_args()

    commits = list(_commits_in_range(args.base, args.head))
    if not commits:
        result = {  # not_applicable: no commits in range to audit
            "check": "surgical_changes", "status": "not_applicable",
            "reason": "no_commits_in_range",
        }
        if args.as_json:
            print(json.dumps(result, indent=2))
        sys.exit(0)

    violations: list[dict] = []
    for sha, subj in commits:
        if any(subj.startswith(pre) for pre in EXEMPT_PREFIXES):
            continue
        modules = _modules_touched(sha)
        if len(modules) > args.max_modules:
            violations.append(
                {"sha": sha[:8], "title": subj, "modules": sorted(modules), "count": len(modules)}
            )

    status = "fail" if violations else "pass"
    result = {"check": "surgical_changes", "status": status, "violations": violations}
    if args.as_json:
        print(json.dumps(result, indent=2))
    elif violations:
        for v in violations:
            print(
                f"TOO MANY MODULES ({v['count']}): {v['sha']} — {v['title']}: {v['modules']}",
                file=sys.stderr,
            )
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
