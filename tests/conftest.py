"""Pytest global test environment configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Prevent accidentally-added root-level test_*.py files from being collected.
# All tests must live in tests/unit/, tests/integration/, or tests/e2e/.
collect_ignore_glob = ["test_*.py"]


def _set_env_if_blank(name: str, value: str) -> None:
    """Set an env var when it is absent or present-but-empty."""
    if value and not os.environ.get(name):
        os.environ[name] = value


# Tests run in non-prod mode so strict production fail-fast gates do not
# block deterministic local/in-process test execution.
os.environ.setdefault("HI_AGENT_ENV", "dev")
os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")

# ---------------------------------------------------------------------------
# Load config/llm_config.json (volces provider) and expose as env vars so
# live_api tests run without requiring manual env var setup.
# Real non-empty env vars always take precedence.
# ---------------------------------------------------------------------------
_LLM_CONFIG = Path(__file__).parent.parent / "config" / "llm_config.json"
if _LLM_CONFIG.exists():
    _volces = json.loads(_LLM_CONFIG.read_text()).get("providers", {}).get("volces", {})
    _set_env_if_blank("VOLCE_API_KEY", _volces.get("api_key", ""))
    _set_env_if_blank("VOLCE_BASE_URL", _volces.get("base_url", ""))

# ---------------------------------------------------------------------------
# Wire Volces Ark into the production LLM gateway path.
# Primary: Anthropic-compatible endpoint (AnthropicLLMGateway).
# Fallback: OpenAI-compatible endpoint (HttpLLMGateway).
# Real non-empty env vars always win.
# ---------------------------------------------------------------------------
_volce_key_val = os.environ.get("VOLCE_API_KEY", "")
_volce_url_val = os.environ.get("VOLCE_BASE_URL", "")
if _volce_key_val:
    _volce_model = (_volces.get("all_models") or ["doubao-seed-2.0-code"])[0]
    _volce_anthropic_url = _volces.get(
        "anthropic_base_url", "https://ark.cn-beijing.volces.com/api/coding"
    )
    # Anthropic-compatible path (primary — cleaner SDK integration)
    # GitHub Actions injects missing secrets as empty strings; treat those as absent.
    _set_env_if_blank("ANTHROPIC_API_KEY", _volce_key_val)
    _set_env_if_blank("HI_AGENT_ANTHROPIC_BASE_URL", _volce_anthropic_url)
    _set_env_if_blank("HI_AGENT_ANTHROPIC_DEFAULT_MODEL", _volce_model)
    # OpenAI-compatible path (fallback)
    _set_env_if_blank("OPENAI_API_KEY", _volce_key_val)
    if _volce_url_val:
        _set_env_if_blank("HI_AGENT_OPENAI_BASE_URL", _volce_url_val)
    _set_env_if_blank("HI_AGENT_OPENAI_DEFAULT_MODEL", _volce_model)
