"""check_doc_canonical_symbols.py - verify that Python symbols in doc code blocks exist.

Scans docs/**/*.md for fenced Python code blocks, extracts
`from hi_agent... import ...` statements and `hi_agent.XXX.YYY(...)`
call expressions, then verifies each symbol is importable and is not a
shim (does not carry a __deprecated__ attribute).

Exit codes:
    0 - all checked symbols are canonical and accessible
    1 - one or more phantoms or stale shims detected

Usage:
    python scripts/check_doc_canonical_symbols.py
    python scripts/check_doc_canonical_symbols.py --json
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

# Ensure local hi_agent/ and agent_kernel/ take precedence over any system-installed packages.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DOCS_ROOT = REPO_ROOT / "docs"
DOC_GLOB = "**/*.md"

# Files / directories to skip entirely (generated evidence and release artifacts)
SKIP_DIRS = {
    DOCS_ROOT / "releases",
    DOCS_ROOT / "delivery",
    DOCS_ROOT / "verification",
    DOCS_ROOT / "governance",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FENCED_PYTHON_BLOCK_RE = re.compile(
    r"```(?:python|py)\n(.*?)```",
    re.DOTALL,
)

# Matches: from hi_agent.foo.bar import Baz, Qux
# Uses comma-separated word list to avoid greedily consuming blank lines and variable assignments.
_FROM_IMPORT_RE = re.compile(
    r"from\s+(hi_agent(?:\.\w+)*)\s+import\s+(\w+(?:\s*,\s*\w+)*)"
)

# Matches: hi_agent.foo.bar.baz(  or  hi_agent.foo.bar.baz  (as attribute ref)
_ATTR_CALL_RE = re.compile(
    r"(hi_agent(?:\.\w+)+)"
)


def _collect_doc_files() -> list[Path]:
    files: list[Path] = []

    if DOCS_ROOT.exists():
        for p in sorted(DOCS_ROOT.glob(DOC_GLOB)):
            if p.is_file():
                files.append(p)

    # Deduplicate while preserving order
    seen: set[Path] = set()
    result: list[Path] = []
    for p in files:
        rp = p.resolve()
        if rp in seen:
            continue
        # Skip any path under a skip directory
        skip = False
        for sd in SKIP_DIRS:
            try:
                rp.relative_to(sd.resolve())
                skip = True
                break
            except ValueError:
                pass
        if skip:
            continue
        seen.add(rp)
        result.append(p)
    return result


def _extract_python_snippets(text: str) -> list[str]:
    return _FENCED_PYTHON_BLOCK_RE.findall(text)


def _parse_symbols(snippet: str) -> list[tuple[str, str]]:
    """Return list of (module_path, attr_name) pairs found in snippet.

    Only looks at `from hi_agent...` imports and `hi_agent.X.Y` expressions.
    """
    symbols: list[tuple[str, str]] = []

    for match in _FROM_IMPORT_RE.finditer(snippet):
        module_path = match.group(1).strip()
        names_raw = match.group(2)
        for name in re.split(r"[\s,]+", names_raw):
            name = name.strip()
            if name:
                symbols.append((module_path, name))

    for match in _ATTR_CALL_RE.finditer(snippet):
        dotted = match.group(1).rstrip("(").rstrip()
        parts = dotted.rsplit(".", 1)
        if len(parts) == 2:
            module_path, attr = parts
            symbols.append((module_path, attr))

    return symbols


def _check_symbol(module_path: str, attr_name: str) -> tuple[str, str | None]:
    """Return ("ok"|"phantom"|"stale", detail).

    "ok"      - symbol exists and is not marked deprecated
    "phantom" - module or attr not importable
    "stale"   - symbol exists but carries __deprecated__ attribute (shim)
    """
    # Try the full dotted path as a module/package first (e.g. hi_agent.plugin is a package).
    full_path = f"{module_path}.{attr_name}"
    try:
        importlib.import_module(full_path)
        return ("ok", None)
    except ImportError:
        pass  # Not a package; fall through to attribute check.

    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        return ("phantom", f"Cannot import {module_path!r}: {exc}")

    _sentinel = object()
    obj = getattr(mod, attr_name, _sentinel)
    if obj is _sentinel:
        return ("phantom", f"{module_path}.{attr_name} does not exist")

    if getattr(obj, "__deprecated__", False):
        return ("stale", f"{module_path}.{attr_name} carries __deprecated__=True")

    return ("ok", None)


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def run_check() -> dict:
    files = _collect_doc_files()

    phantoms: list[dict] = []
    stale: list[dict] = []

    for doc_file in files:
        try:
            text = doc_file.read_text(encoding="utf-8")
        except OSError:
            continue

        snippets = _extract_python_snippets(text)
        for snippet in snippets:
            symbols = _parse_symbols(snippet)
            for module_path, attr_name in symbols:
                status, detail = _check_symbol(module_path, attr_name)
                entry = {
                    "file": str(doc_file.relative_to(REPO_ROOT)),
                    "symbol": f"{module_path}.{attr_name}",
                    "detail": detail,
                }
                if status == "phantom":
                    phantoms.append(entry)
                elif status == "stale":
                    stale.append(entry)

    overall = "pass" if not phantoms and not stale else "fail"
    return {
        "check": "doc_canonical",
        "status": overall,
        "phantoms": phantoms,
        "stale": stale,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check doc code blocks reference real symbols.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args()

    result = run_check()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["status"] == "pass":
            print("doc_canonical: PASS - all checked symbols exist and are canonical.")
        else:
            print("doc_canonical: FAIL")
            if result["phantoms"]:
                print(f"\nPhantom symbols ({len(result['phantoms'])}):")
                for entry in result["phantoms"]:
                    print(f"  [{entry['file']}] {entry['symbol']}")
                    print(f"    {entry['detail']}")
            if result["stale"]:
                print(f"\nStale shims ({len(result['stale'])}):")
                for entry in result["stale"]:
                    print(f"  [{entry['file']}] {entry['symbol']}")
                    print(f"    {entry['detail']}")

    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
