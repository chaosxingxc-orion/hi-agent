"""Pytest global test environment configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Tests run in non-prod mode so strict production fail-fast gates do not
# block deterministic local/in-process test execution.
os.environ.setdefault("HI_AGENT_ENV", "dev")
os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")

# ---------------------------------------------------------------------------
# Load config/llm_config.json (volces provider) and expose as env vars so
# live_api tests run without requiring manual env var setup.
# Real env vars always take precedence (setdefault never overwrites).
# ---------------------------------------------------------------------------
_LLM_CONFIG = Path(__file__).parent.parent / "config" / "llm_config.json"
if _LLM_CONFIG.exists():
    _volces = json.loads(_LLM_CONFIG.read_text()).get("providers", {}).get("volces", {})
    os.environ.setdefault("VOLCE_API_KEY", _volces.get("api_key", ""))
    os.environ.setdefault("VOLCE_BASE_URL", _volces.get("base_url", ""))

# ---------------------------------------------------------------------------
# Wire Volces Ark (OpenAI-compatible) into the production LLM gateway path.
# HttpLLMGateway uses openai_base_url + openai_api_key_env — both configurable.
# This lets test_prod_e2e.py run with real LLM calls without OpenAI/Anthropic keys.
# Real env vars always win (setdefault never overwrites).
# ---------------------------------------------------------------------------
_volce_key_val = os.environ.get("VOLCE_API_KEY", "")
_volce_url_val = os.environ.get("VOLCE_BASE_URL", "")
if _volce_key_val and _volce_url_val:
    _volce_model = (_volces.get("all_models") or ["doubao-seed-2.0-code"])[0]
    os.environ.setdefault("OPENAI_API_KEY", _volce_key_val)
    os.environ.setdefault("HI_AGENT_OPENAI_BASE_URL", _volce_url_val)
    os.environ.setdefault("HI_AGENT_LLM_DEFAULT_PROVIDER", "openai")
    os.environ.setdefault("HI_AGENT_OPENAI_DEFAULT_MODEL", _volce_model)
