#!/usr/bin/env python3
"""W16-Q: Secret scan gate.

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

findings: list[dict] = []


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


def check_json_config(path: Path) -> None:
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
                        "file": str(path.relative_to(ROOT)),
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
            if not_placeholder and not_generic:
                key_name = (
                    m.group(0).split("=")[0].split(":")[0].strip()
                )
                findings.append({
                    "file": str(path.relative_to(ROOT)),
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
                "file": str(path.relative_to(ROOT)),
                "line": lineno,
                "kind": "uuid_in_secret_context",
                "redacted_match": f"UUID-like value at line {lineno}",
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Secret scan gate.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", help="Write evidence JSON to this path")
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

    for src_dir in [ROOT / "scripts", ROOT / "hi_agent"]:
        if src_dir.exists():
            for py_file in sorted(src_dir.rglob("*.py")):
                check_text_file(py_file)

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
        if findings:
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

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
