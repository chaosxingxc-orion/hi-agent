#!/usr/bin/env python3
"""Validate the agent-kernel dependency pin in pyproject.toml.

Checks:
1) The dependency exists and is a git URL with an explicit revision.
2) The revision resolves on the remote repository.
3) (Default) The pinned revision equals remote main HEAD.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover
    raise RuntimeError("Python 3.11+ is required (missing tomllib).") from exc


HEX40_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def run_git(*args: str) -> str:
    """Run a git command and return stdout."""
    try:
        out = subprocess.check_output(
            ["git", *args],
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        output = (exc.output or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {output}") from exc
    return out


def parse_dependency(pyproject: Path, package: str) -> str:
    """Read dependency string for package from pyproject.toml."""
    data: dict[str, Any] = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    if not isinstance(deps, list):
        raise RuntimeError("`project.dependencies` must be a list.")
    prefix = f"{package} @ "
    for dep in deps:
        if isinstance(dep, str) and dep.startswith(prefix):
            return dep
    raise RuntimeError(f"Dependency not found: {package}")


def split_git_dependency(dep: str, package: str) -> tuple[str, str]:
    """Split `package @ git+URL@revision` into (url, revision)."""
    prefix = f"{package} @ "
    spec = dep[len(prefix) :].strip()
    if not spec.startswith("git+"):
        raise RuntimeError(f"{package} dependency must use git+, got: {spec}")
    spec = spec[len("git+") :]
    if "@" not in spec:
        raise RuntimeError(f"{package} dependency must pin a revision with @.")
    url, revision = spec.rsplit("@", 1)
    url = url.strip()
    revision = revision.strip()
    if not url or not revision:
        raise RuntimeError(f"Invalid dependency spec: {dep}")
    return url, revision


def resolve_revision_to_commit(url: str, revision: str) -> str:
    """Resolve revision (tag/branch/ref/sha) to a commit SHA."""
    all_refs = run_git("ls-remote", url).splitlines()
    ref_map: dict[str, str] = {}
    for line in all_refs:
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        ref_map[ref] = sha

    if HEX40_RE.fullmatch(revision):
        if any(sha == revision for sha in ref_map.values()):
            return revision.lower()
        raise RuntimeError(f"Pinned commit not found on remote: {revision}")

    candidate_refs = [
        revision,
        f"refs/heads/{revision}",
        f"refs/tags/{revision}",
        f"refs/tags/{revision}^{{}}",
    ]
    for ref in candidate_refs:
        sha = ref_map.get(ref)
        if sha:
            return sha.lower()
    raise RuntimeError(f"Could not resolve revision on remote: {revision}")


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml (default: pyproject.toml)",
    )
    parser.add_argument(
        "--package",
        default="agent-kernel",
        help="Dependency package name (default: agent-kernel)",
    )
    parser.add_argument(
        "--main-ref",
        default="refs/heads/main",
        help="Remote ref considered latest (default: refs/heads/main)",
    )
    parser.add_argument(
        "--allow-non-head",
        action="store_true",
        help="Only verify pin is resolvable; skip latest-main-head check.",
    )
    args = parser.parse_args()

    pyproject = Path(args.pyproject)
    if not pyproject.exists():
        raise RuntimeError(f"File not found: {pyproject}")

    dep = parse_dependency(pyproject, args.package)
    url, revision = split_git_dependency(dep, args.package)
    pinned_commit = resolve_revision_to_commit(url, revision)

    head_line = run_git("ls-remote", url, args.main_ref).strip()
    if not head_line:
        raise RuntimeError(f"Failed to resolve main ref: {args.main_ref}")
    main_head = head_line.split()[0].lower()

    if not args.allow_non_head and pinned_commit != main_head:
        raise RuntimeError(
            f"{args.package} pin is not latest main.\n"
            f"  pinned: {pinned_commit}\n"
            f"  {args.main_ref}: {main_head}"
        )

    print(
        f"{args.package} pin OK: {pinned_commit}"
        + ("" if not args.allow_non_head else " (non-head allowed)")
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
