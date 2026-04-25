"""Script to add required RunExecutor args to all test files.

After Rule 6 hardening in runner.py, these 5 args are now required:
  - event_emitter
  - compressor
  - acceptance_policy
  - cts_budget
  - policy_versions

This script finds all RunExecutor( calls in test files and adds the
missing required args with their default constructors. It also adds
the necessary imports.
"""

from __future__ import annotations

import os
import re
import sys

# Map arg name -> constructor call to inject
REQUIRED_ARGS: dict[str, str] = {
    "event_emitter": "EventEmitter()",
    "compressor": "MemoryCompressor()",
    "acceptance_policy": "AcceptancePolicy()",
    "cts_budget": "CTSExplorationBudget()",
    "policy_versions": "PolicyVersionSet()",
}

# Import statement needed for each arg class
ARG_IMPORTS: dict[str, str] = {
    "event_emitter": "from hi_agent.events import EventEmitter",
    "compressor": "from hi_agent.memory import MemoryCompressor",
    "acceptance_policy": "from hi_agent.route_engine.acceptance import AcceptancePolicy",
    "cts_budget": "from hi_agent.contracts import CTSExplorationBudget",
    "policy_versions": "from hi_agent.contracts.policy import PolicyVersionSet",
}

# Import detection patterns for each class
IMPORT_PATTERNS: dict[str, str] = {
    "event_emitter": r"EventEmitter",
    "compressor": r"MemoryCompressor",
    "acceptance_policy": r"AcceptancePolicy",
    "cts_budget": r"CTSExplorationBudget",
    "policy_versions": r"PolicyVersionSet",
}


def find_test_files(root: str) -> list[str]:
    """Return all .py files under root that contain RunExecutor(."""
    result = []
    for dirpath, _dirs, fnames in os.walk(root):
        for fname in fnames:
            if fname.endswith(".py"):
                path = os.path.join(dirpath, fname)
                try:
                    with open(path, encoding="utf-8", errors="replace") as _fh:
                        content = _fh.read()
                except OSError:
                    continue
                if "RunExecutor(" in content:
                    result.append(path)
    return sorted(result)


def find_runexecutor_call_ranges(content: str) -> list[tuple[int, int]]:
    """Return (start, end) char ranges of RunExecutor(...) call text.

    Each range covers from 'RunExecutor(' to the matching closing ')'.
    """
    ranges = []
    pos = 0
    while True:
        idx = content.find("RunExecutor(", pos)
        if idx == -1:
            break
        # Find matching closing paren
        depth = 0
        i = idx + len("RunExecutor(")
        depth = 1
        in_string = None
        escape_next = False
        while i < len(content) and depth > 0:
            ch = content[i]
            if escape_next:
                escape_next = False
                i += 1
                continue
            if in_string:
                if ch == "\\":
                    escape_next = True
                elif ch == in_string:
                    in_string = None
            else:
                if ch in ('"', "'"):
                    in_string = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            i += 1
        if depth == 0:
            ranges.append((idx, i))  # i is past the closing ')'
        pos = idx + 1
    return ranges


def args_present_in_call(call_text: str) -> set[str]:
    """Return the set of arg names present as keyword args in this call."""
    found = set()
    for arg in REQUIRED_ARGS:
        # keyword arg pattern: 'argname=' with optional whitespace
        if re.search(r"\b" + arg + r"\s*=", call_text):
            found.add(arg)
    return found


def has_kwargs_splat(call_text: str) -> bool:
    """Return True if call contains **kwargs or **defaults style splat."""
    return "**" in call_text


def inject_args_into_call(call_text: str, missing_args: list[str]) -> str:
    """Add missing keyword args before the last ')' of the call.

    Inserts them as keyword args at the end, preserving trailing comma style.
    Skips calls with **kwargs splats (those are handled separately).
    """
    if has_kwargs_splat(call_text):
        # Cannot inject after **kwargs — caller must handle via setdefault
        return call_text

    # Find the position of the last ')' (closing paren of RunExecutor call)
    # call_text ends with ')'
    assert call_text.endswith(")")
    body = call_text[len("RunExecutor(") : -1]  # strip 'RunExecutor(' and final ')'

    # Build the injection string
    injected = ", ".join(f"{arg}={REQUIRED_ARGS[arg]}" for arg in missing_args)

    # Determine whether to add a leading comma
    # Strip trailing whitespace from body to check if it ends with ','
    stripped = body.rstrip()
    if not stripped or stripped.endswith(","):
        # body is empty or ends with comma — just append with space
        new_body = body + f"{injected}"
    else:
        # body ends with a value — need a comma before injected args
        new_body = body + f", {injected}"

    return f"RunExecutor({new_body})"


def ensure_imports(content: str, original: str, needed_args: set[str]) -> str:
    """Add missing import statements for needed arg classes.

    Inserts them after the last existing 'from hi_agent...' import block,
    or before the first non-import line if no hi_agent import exists.
    Uses the original content to determine what was already imported.
    """
    for arg in sorted(needed_args):
        import_line = ARG_IMPORTS[arg]
        class_name = IMPORT_PATTERNS[arg]
        # Skip if the import statement is already present in original
        # (check import line, not just class name, to avoid false positives from usage)
        if import_line in original:
            continue
        # Also skip if the class is imported from any source in original
        if re.search(r"\bimport\b.*\b" + class_name + r"\b", original):
            continue
        # Find insertion point: after last 'from hi_agent' import in current content
        lines = content.splitlines(keepends=True)
        insert_idx = None
        for i, line in enumerate(lines):
            if line.startswith("from hi_agent") or line.startswith("import hi_agent"):
                insert_idx = i
        if insert_idx is not None:
            lines.insert(insert_idx + 1, import_line + "\n")
        else:
            # Find first non-blank, non-comment, non-docstring line
            for i, line in enumerate(lines):
                stripped = line.strip()
                if (
                    stripped
                    and not stripped.startswith("#")
                    and not stripped.startswith('"""')
                    and not stripped.startswith("'''")
                ):
                    lines.insert(i, import_line + "\n")
                    break
        content = "".join(lines)
    return content


def process_file(path: str, dry_run: bool = False) -> bool:
    """Process one file. Returns True if modified."""
    try:
        with open(path, encoding="utf-8") as _fh:
            original = _fh.read()
    except (OSError, UnicodeDecodeError):
        try:
            with open(path, encoding="utf-8", errors="replace") as _fh:
                original = _fh.read()
        except OSError:
            print(f"  SKIP (read error): {path}")
            return False

    content = original
    modified = False

    # Find all RunExecutor( call ranges
    ranges = find_runexecutor_call_ranges(content)
    if not ranges:
        return False

    # Process in reverse order to preserve character positions
    for start, end in reversed(ranges):
        call_text = content[start:end]
        present = args_present_in_call(call_text)
        missing = [arg for arg in REQUIRED_ARGS if arg not in present]
        if not missing:
            continue

        new_call = inject_args_into_call(call_text, missing)
        content = content[:start] + new_call + content[end:]
        modified = True

    if not modified:
        return False

    # Now ensure imports are present for all args we added
    # Re-scan to find which args we added
    needed_imports: set[str] = set()
    for arg in REQUIRED_ARGS:
        class_name = IMPORT_PATTERNS[arg]
        # If class appears in new content but not in original, we added it
        if class_name + "()" in content and class_name not in original:
            needed_imports.add(arg)

    if needed_imports:
        content = ensure_imports(content, original, needed_imports)

    if not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  UPDATED: {path}")
    else:
        print(f"  WOULD UPDATE: {path}")

    return True


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    tests_root = "tests"
    files = find_test_files(tests_root)
    print(f"Found {len(files)} files with RunExecutor(")
    updated = 0
    for path in files:
        if process_file(path, dry_run=dry_run):
            updated += 1
    print(f"\nDone. Updated {updated}/{len(files)} files.")


if __name__ == "__main__":
    main()
