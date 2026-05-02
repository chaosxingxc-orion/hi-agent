#!/usr/bin/env python3
"""Secret scan gate.

Scans tracked repository files for accidentally committed API secrets.

Checks:
- config/llm_config.json: non-empty api_key/token/secret fields
- docs/delivery/*.json: UUID-like or high-entropy strings in key fields
- docs/downstream-responses/*.md: UUID patterns in suspicious context
- scripts/ and hi_agent/: key=value patterns with real-looking secrets

Exit 0: pass (no secrets found)
Exit 1: fail (potential secret found)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_KEY_FIELD_RE = re.compile(
    r"(?:api_key|apiKey|api_secret|access_key|secret_key"
    r"|VOLCES_API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY)"
    r"\s*[=:]\s*[\"']?([A-Za-z0-9\\-_./+]{16,})[\"']?",
    re.IGNORECASE,
)
_SUSPICIOUS_DICT_KEYS = {
    "api_key", "apikey", "api_secret", "token", "secret", "password", "access_key",
}
_PLACEHOLDERS = {
    "<api_key>", "your-key-here", "xxx", "placeholder", "example", "replace-me",
    "sk-...", "",
}
# NOTE (W24-J1, 2026-04-30): Previously llm_config.json was skipped because a dev
# Volces key was committed in plaintext. That was a security defect (HD-1). The
# skip is removed; llm_config.json is now scanned like any other config file. The
# api_key fields must be empty strings or env-var placeholders. Real keys live
# only in llm_config.local.json (gitignored).
_SKIP_JSON_CONFIG_PATHS: set[str] = set()
# Code expression prefixes: values starting with these are code, not secrets.
_CODE_EXPR_STARTS = (
    "self.", "cls.", "get_", "load_", "build_", "os.", "env.", "config.",
    "settings.", "environ", "resolve",
)
# UUID in API-key context: matches when a recognized secret-adjacent keyword
# and a UUID-format value appear on the same line. Catches patterns like
# "Rotate Volces API key f103e564-61c5-..." in docs/releases JSON files.
_SECRET_CONTEXT_WORDS_RE = re.compile(
    r"\b(?:api[_\s]?key|api_secret|secret_key|access_key|secret|token"
    r"|volces|anthropic|openai|VOLCES_API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY)\b",
    re.IGNORECASE,
)

findings: list[dict] = []


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


def check_json_config(path: Path) -> None:
    rel = _rel(path)
    if rel in _SKIP_JSON_CONFIG_PATHS:
        return  # intentionally committed dev config; user is aware
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    def _scan(obj: object, path_prefix: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                key_lower = k.lower()
                if (
                    key_lower in _SUSPICIOUS_DICT_KEYS
                    and isinstance(v, str)
                    and v.strip()
                    and v.strip().lower() not in _PLACEHOLDERS
                ):
                    findings.append({
                        "file": _rel(path),
                        "line": 0,
                        "kind": "api_key_in_config",
                        "redacted_match": f"{k}={_redact(v)}",
                    })
                _scan(v, f"{path_prefix}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _scan(item, f"{path_prefix}[{i}]")

    _scan(data)


def check_text_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("#", "//")) or not stripped:
            continue
        for m in _KEY_FIELD_RE.finditer(line):
            value = m.group(1).strip()
            not_placeholder = value.lower() not in _PLACEHOLDERS
            not_generic = not any(
                p in value.lower() for p in ("placeholder", "example", "xxx", "your")
            )
            is_code_expr = any(value.lower().startswith(p) for p in _CODE_EXPR_STARTS)
            # Method-chained expressions (foo.bar) are code, not keys; real keys lack dots.
            has_dot_chain = "." in value and not value.startswith(".")
            if not_placeholder and not_generic and not is_code_expr and not has_dot_chain:
                key_name = (
                    m.group(0).split("=")[0].split(":")[0].strip()
                )
                findings.append({
                    "file": _rel(path),
                    "line": lineno,
                    "kind": "secret_in_source",
                    "redacted_match": f"{key_name}={_redact(value)}",
                })


def check_md_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    placeholders = ("<sha>", "{{", "example", "placeholder", "xxx")
    for lineno, line in enumerate(lines, 1):
        line_lower = line.lower()
        has_key_word = any(w in line_lower for w in _SUSPICIOUS_DICT_KEYS)
        has_uuid = _UUID_RE.search(line)
        is_placeholder = any(p in line.lower() for p in placeholders)
        if has_key_word and has_uuid and not is_placeholder:
            findings.append({
                "file": _rel(path),
                "line": lineno,
                "kind": "uuid_in_secret_context",
                "redacted_match": f"UUID-like value at line {lineno}",
            })


def check_releases_file(path: Path) -> None:
    """Scan a docs/releases file for UUID in API-key context (GOV-A W28)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for lineno, line in enumerate(lines, 1):
        if not _SECRET_CONTEXT_WORDS_RE.search(line):
            continue
        uuid_m = _UUID_RE.search(line)
        if uuid_m:
            findings.append({
                "file": _rel(path),
                "line": lineno,
                "kind": "uuid_in_secret_context",
                "redacted_match": f"API-key UUID at line {lineno}: {uuid_m.group()[:8]}***",
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Secret scan gate.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", help="Write evidence JSON to this path")
    parser.add_argument("--strict", action="store_true",
                        help="Treat absent input as fail rather than not_applicable")
    args = parser.parse_args()

    for config_path in [ROOT / "config" / "llm_config.json"]:
        if config_path.exists():
            check_json_config(config_path)

    delivery_dir = ROOT / "docs" / "delivery"
    if delivery_dir.exists():
        for delivery_json in delivery_dir.glob("*.json"):
            check_text_file(delivery_json)

    downstream_dir = ROOT / "docs" / "downstream-responses"
    if downstream_dir.exists():
        for md_file in downstream_dir.glob("*.md"):
            check_md_file(md_file)

    releases_dir = ROOT / "docs" / "releases"
    if releases_dir.exists():
        for releases_file in sorted(releases_dir.rglob("*.json")):
            check_releases_file(releases_file)
        for releases_file in sorted(releases_dir.rglob("*.md")):
            check_md_file(releases_file)

    for src_dir in [ROOT / "scripts", ROOT / "hi_agent"]:
        if src_dir.exists():
            for py_file in sorted(src_dir.rglob("*.py")):
                check_text_file(py_file)

    # Determine if any source dirs were actually scanned.
    _src_dirs_present = any(
        (ROOT / d).exists() for d in ("scripts", "hi_agent", "config")
    )
    if not _src_dirs_present and not findings:
        if args.strict:
            print("FAIL (strict): input absent at scripts/hi_agent/config; "
                  "in strict mode, absent input is a defect", file=sys.stderr)
            return 1
        status = "not_applicable"
    else:
        status = "pass" if not findings else "fail"

    result = {
        "check": "secret_scan",
        "status": status,
        "findings_count": len(findings),
        "findings": findings,
    }

    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if status == "not_applicable":
            print("NOT_APPLICABLE: no source directories found to scan")
        elif findings:
            print("FAIL: potential secrets found:")
            for f in findings:
                print(f"  [{f['kind']}] {f['file']}:{f['line']} -- {f['redacted_match']}")
            print("\nEnsure api_key fields in config files are empty (\"\").")
            print(
                "Use 'git update-index --skip-worktree config/llm_config.json' "
                "to protect local config."
            )
        else:
            print("PASS: no secrets found in tracked files")

    if status == "not_applicable":
        return 2
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
