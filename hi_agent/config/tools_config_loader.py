"""Load custom tool registrations from config/tools.json into CapabilityRegistry."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hi_agent.capability.registry import CapabilityRegistry

logger = logging.getLogger(__name__)

_DEFAULT_TOOLS_JSON = Path(__file__).parent.parent.parent / "config" / "tools.json"


class ConfigValidationError(ValueError):
    """Raised when tools.json contains invalid entries."""


def load_tools_from_config(
    registry: CapabilityRegistry,
    *,
    config_path: Path | str | None = None,
) -> int:
    """Load tool specs from config_path (default config/tools.json) into registry.

    Returns the number of tools successfully registered.
    Each invalid entry is collected; all violations raise ConfigValidationError together.
    """
    path = Path(config_path) if config_path is not None else _DEFAULT_TOOLS_JSON
    if not path.exists():
        return 0  # no custom tools file — not an error

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"tools.json is not valid JSON: {exc}") from exc

    tools = raw.get("tools", [])
    if not isinstance(tools, list):
        raise ConfigValidationError("tools.json: 'tools' must be a list")

    errors: list[str] = []
    registered = 0
    for i, spec in enumerate(tools):
        try:
            _register_one_tool(registry, spec, index=i)
            registered += 1
        except ConfigValidationError as exc:
            errors.append(str(exc))

    if errors:
        raise ConfigValidationError(
            f"tools.json has {len(errors)} invalid entry(s):\n" + "\n".join(errors)
        )

    logger.info(
        "load_tools_from_config: registered %d custom tool(s) from %s.", registered, path
    )
    return registered


def _register_one_tool(
    registry: CapabilityRegistry,
    spec: Any,
    *,
    index: int,
) -> None:
    """Validate and register a single tool spec into the registry."""
    if not isinstance(spec, dict):
        raise ConfigValidationError(
            f"tools[{index}]: must be a dict, got {type(spec).__name__}"
        )
    name = spec.get("name")
    if not name or not isinstance(name, str):
        raise ConfigValidationError(
            f"tools[{index}]: 'name' is required and must be a string"
        )
    description = spec.get("description", "")
    handler_cfg = spec.get("handler")
    if not isinstance(handler_cfg, dict):
        raise ConfigValidationError(
            f"tools[{index}] ({name!r}): 'handler' must be a dict"
        )
    handler_type = handler_cfg.get("type")
    if handler_type not in ("http", "shell", "python"):
        raise ConfigValidationError(
            f"tools[{index}] ({name!r}): handler.type must be 'http', 'shell', or 'python'"
        )

    handler_fn = _build_handler(name, handler_cfg, handler_type)

    from hi_agent.capability.registry import CapabilitySpec

    cap_spec = CapabilitySpec(
        name=name,
        description=description,
        parameters=spec.get("input_schema", {}),
        handler=handler_fn,
    )
    registry.register(cap_spec)


def _build_handler(name: str, handler_cfg: dict, handler_type: str):
    """Return a callable that executes the handler described by handler_cfg."""
    if handler_type == "http":
        url = handler_cfg.get("url", "")
        if not url:
            raise ConfigValidationError(f"tool {name!r}: http handler requires 'url'")
        method = handler_cfg.get("method", "POST").upper()
        timeout = float(handler_cfg.get("timeout_s", 30.0))

        def _http_handler(**kwargs: Any) -> Any:
            import httpx

            resp = httpx.request(method, url, json=kwargs, timeout=timeout)
            resp.raise_for_status()
            return resp.json()

        return _http_handler

    if handler_type == "shell":
        cmd_template = handler_cfg.get("command", "")
        if not cmd_template:
            raise ConfigValidationError(f"tool {name!r}: shell handler requires 'command'")
        allowed_args = set(handler_cfg.get("allowed_args", []))

        # shell=True is explicitly FORBIDDEN per security policy.
        def _shell_handler(**kwargs: Any) -> Any:
            import shlex
            import subprocess

            filtered = (
                {k: v for k, v in kwargs.items() if k in allowed_args}
                if allowed_args
                else kwargs
            )
            parts = shlex.split(cmd_template)
            parts += [f"--{k}={v}" for k, v in filtered.items()]
            result = subprocess.run(
                parts, capture_output=True, text=True, shell=False, timeout=60
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }

        return _shell_handler

    if handler_type == "python":
        module_func = handler_cfg.get("callable", "")
        if ":" not in module_func:
            raise ConfigValidationError(
                f"tool {name!r}: python handler 'callable' must be 'module:func'"
            )
        module_name, func_name = module_func.rsplit(":", 1)

        def _python_handler(**kwargs: Any) -> Any:
            import importlib

            mod = importlib.import_module(module_name)
            fn = getattr(mod, func_name)
            return fn(**kwargs)

        return _python_handler

    raise ConfigValidationError(f"tool {name!r}: unsupported handler type {handler_type!r}")
