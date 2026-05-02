"""Secret-safe live LLM config loader for e2e tests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "llm_config.json"


@dataclass(frozen=True, slots=True)
class LiveLLMConfig:
    """Resolved live LLM settings for the Volces gateway path."""

    mode: str
    provider: str
    api_key: str
    base_url: str
    default_model: str
    timeout_seconds: float
    max_retries: int
    config_path: Path

    @property
    def live_enabled(self) -> bool:
        """Return True when the config permits a live call path."""
        return self.mode != "heuristic" and bool(self.api_key)

    @property
    def enabled(self) -> bool:
        """Backward-compatible alias used by the e2e fixtures."""
        return self.live_enabled

    def __repr__(self) -> str:
        return (
            "LiveLLMConfig("
            f"mode={self.mode!r}, "
            f"provider={self.provider!r}, "
            f"base_url={self.base_url!r}, "
            f"default_model={self.default_model!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"max_retries={self.max_retries!r}, "
            f"live_enabled={self.live_enabled!r}, "
            f"api_key_present={bool(self.api_key)!r}"
            ")"
        )

    __str__ = __repr__


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    return ""


def _coerce_int(value: object, default: int) -> int:
    try:
        if isinstance(value, str) and not value.strip():
            return default
        return int(value)  # type: ignore[arg-type]  expiry_wave: Wave 30
    except (TypeError, ValueError):
        return default


def _coerce_float(value: object, default: float) -> float:
    try:
        if isinstance(value, str) and not value.strip():
            return default
        return float(value)  # type: ignore[arg-type]  expiry_wave: Wave 30
    except (TypeError, ValueError):
        return default


def _normalize_mode(raw_mode: str, api_key: str, provider: str) -> str:
    mode = raw_mode.strip().lower()
    if mode in {"heuristic", "off", "disabled"}:
        return "heuristic"
    if mode in {"real", "volces"}:
        return mode
    if api_key:
        return "volces" if provider == "volces" else "real"
    return "heuristic"


def load_live_llm_config(config_path: str | Path | None = None) -> LiveLLMConfig:
    """Load live LLM config from JSON plus environment overrides."""

    path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH
    data = _read_json(path)
    providers = data.get("providers", {}) if isinstance(data.get("providers", {}), dict) else {}
    provider_name = str(data.get("default_provider", "volces") or "volces").strip().lower()
    provider_cfg = providers.get(provider_name, {})
    if not isinstance(provider_cfg, dict):
        provider_cfg = {}

    api_key = str(provider_cfg.get("api_key", "") or "")
    base_url = _env_value("VOLCE_BASE_URL") or str(provider_cfg.get("base_url", "") or "")

    models_obj = provider_cfg.get("models", {})
    models = models_obj if isinstance(models_obj, dict) else {}
    default_model = (
        _env_value("VOLCE_DEFAULT_MODEL")
        or str(models.get("strong", "") or "")
        or str(models.get("medium", "") or "")
        or str(models.get("light", "") or "")
    )

    timeout_seconds = _coerce_float(
        _env_value("VOLCE_TIMEOUT_SECONDS") or provider_cfg.get("timeout_seconds", 60),
        60.0,
    )
    max_retries = _coerce_int(
        _env_value("VOLCE_MAX_RETRIES") or provider_cfg.get("max_retries", 1),
        1,
    )
    requested_mode = os.environ.get("HI_AGENT_LLM_MODE", "").strip().lower()
    mode = _normalize_mode(requested_mode, api_key, provider_name)

    return LiveLLMConfig(
        mode=mode,
        provider=provider_name,
        api_key=api_key,
        base_url=base_url,
        default_model=default_model,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        config_path=path,
    )


__all__ = ["LiveLLMConfig", "load_live_llm_config"]
