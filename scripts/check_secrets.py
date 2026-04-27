"""Check repository for accidentally committed API secrets.

Scans:
- config/llm_config.json: any non-empty api_key fields
- docs/delivery/*.json: UUID-like or high-entropy strings in key fields
- docs/downstream-responses/*.md: UUID patterns in suspicious context

Usage: python scripts/check_secrets.py [--strict]
Exits 0 if clean, 1 if findings.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Patterns that suggest a real API key (not a placeholder)
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_KEY_FIELD_RE = re.compile(r'"(?:api_key|apiKey|key|token|secret|password)"\s*:\s*"([^"]{8,})"')

SUSPICIOUS_CONTEXT_WORDS = {"api_key", "apikey", "key", "token", "secret", "password", "access_key"}

findings: list[str] = []


def check_json_config(path: Path) -> None:
    """Check a JSON config file for non-empty API key fields."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return

    def _scan(obj: object, path_prefix: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                key_lower = k.lower()
                if key_lower in SUSPICIOUS_CONTEXT_WORDS and isinstance(v, str) and v.strip():
                    findings.append(f"{path}:{path_prefix}.{k} — non-empty secret field")
                _scan(v, f"{path_prefix}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _scan(item, f"{path_prefix}[{i}]")

    _scan(data)


def check_md_file(path: Path) -> None:
    """Scan a markdown file for UUID-like secrets in suspicious context."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for lineno, line in enumerate(lines, 1):
        line_lower = line.lower()
        # Only flag lines that contain both a suspicious keyword and a UUID pattern
        has_key_word = any(w in line_lower for w in SUSPICIOUS_CONTEXT_WORDS)
        if has_key_word and _UUID_RE.search(line):
            # Exclude obvious placeholders
            placeholders = ["<sha>", "{{", "example", "placeholder", "xxx"]
            if any(placeholder in line.lower() for placeholder in placeholders):
                continue
            findings.append(f"{path}:{lineno} — UUID-like value in secret context")


def check_delivery_json(path: Path) -> None:
    """Scan delivery JSON for UUID-like values in key fields."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return

    for m in _KEY_FIELD_RE.finditer(text):
        value = m.group(1)
        alphanum = value.replace("-", "").replace("_", "").isalnum()
        if _UUID_RE.match(value) or (len(value) > 20 and alphanum):
            findings.append(f"{path}: secret-like value in key field: {value[:8]}...")


def main() -> int:
    root = Path(".")

    # Check committed config
    config_path = root / "config" / "llm_config.json"
    if config_path.exists():
        check_json_config(config_path)

    # Check delivery JSONs
    delivery_dir = root / "docs" / "delivery"
    if delivery_dir.exists():
        for delivery_json in delivery_dir.glob("*.json"):
            check_delivery_json(delivery_json)

    # Check downstream response docs
    downstream_dir = root / "docs" / "downstream-responses"
    if downstream_dir.exists():
        for md_file in downstream_dir.glob("*.md"):
            check_md_file(md_file)

    if findings:
        print("SECRETS CHECK FAIL — potential secrets found:")
        for finding in findings:
            print(f"  {finding}")
        print("\nTo fix: ensure api_key fields in config/llm_config.json are empty (\"\").")
        print(
            "Use 'git update-index --skip-worktree config/llm_config.json'"
            " to protect your local copy."
        )
        return 1

    print("SECRETS CHECK OK — no secrets found in tracked files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
