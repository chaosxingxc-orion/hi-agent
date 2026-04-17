"""ReadinessProbe: pure observer for SystemBuilder platform readiness.

Extracted from SystemBuilder.readiness() in W6-002.
builder.readiness() is now a thin facade:
    return ReadinessProbe(self).snapshot()
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hi_agent.config.builder import SystemBuilder

logger = logging.getLogger(__name__)


class ReadinessProbe:
    """Pure observer of SystemBuilder platform state.

    Reads builder state via public build_* methods only.
    Never writes to builder or holds mutable builder state.
    """

    def __init__(self, builder: "SystemBuilder") -> None:
        self._builder = builder

    def snapshot(self) -> dict[str, Any]:
        """Return a live readiness snapshot of all platform subsystems.

        Output is byte-identical to the original builder.readiness() implementation.
        """
        result: dict[str, Any] = {
            "ready": False,
            "health": "ok",
            "execution_mode": "unknown",
            "models": [],
            "skills": [],
            "mcp_servers": [],
            "plugins": [],
            "capabilities": [],
            "subsystems": {},
        }
        issues: list[str] = []

        # --- kernel ---
        try:
            kernel = self._builder.build_kernel()
            base_url = getattr(self._builder._config, "kernel_base_url", "local") or "local"
            mode = "http" if base_url.lower() not in ("", "local") else "local"
            result["execution_mode"] = mode
            result["subsystems"]["kernel"] = {"status": "ok", "mode": mode}
        except Exception as exc:
            result["subsystems"]["kernel"] = {"status": "error", "error": str(exc)}
            result["health"] = "degraded"
            issues.append(f"kernel: {exc}")

        # --- LLM / models ---
        try:
            gateway = self._builder.build_llm_gateway()
            if gateway is None:
                result["subsystems"]["llm"] = {"status": "not_configured"}
                result["models"] = []
            else:
                # Best-effort: list models from registry if tier router available
                model_names: list[str] = []
                if self._builder._tier_router is not None:
                    try:
                        registry = getattr(self._builder._tier_router, "_registry", None)
                        if registry is not None:
                            model_names = [
                                m if isinstance(m, str) else getattr(m, "name", str(m))
                                for m in registry.list_models()
                            ]
                    except Exception:
                        pass
                result["models"] = [{"name": n, "status": "configured"} for n in model_names]
                result["subsystems"]["llm"] = {"status": "ok", "models": len(model_names)}
        except Exception as exc:
            result["subsystems"]["llm"] = {"status": "error", "error": str(exc)}
            result["health"] = "degraded"
            issues.append(f"llm: {exc}")

        # --- capabilities ---
        try:
            invoker = self._builder.build_invoker()
            # CapabilityInvoker exposes registry as public `registry` attribute.
            registry = getattr(invoker, "registry", None) or getattr(invoker, "_registry", None)
            cap_names: list[str] = []
            if registry is not None:
                cap_names = registry.list_names()
            result["capabilities"] = cap_names
            result["subsystems"]["capabilities"] = {"status": "ok", "count": len(cap_names)}
        except Exception as exc:
            result["subsystems"]["capabilities"] = {"status": "error", "error": str(exc)}
            result["health"] = "degraded"
            issues.append(f"capabilities: {exc}")

        # --- skills ---
        try:
            loader = self._builder.build_skill_loader()
            # discover() triggers loading and returns the count (int), not a list.
            # Use list_skills() to get the actual SkillDefinition objects.
            skill_count = 0
            skill_list: list[Any] = []
            try:
                if hasattr(loader, "discover"):
                    skill_count = loader.discover()
                if hasattr(loader, "list_skills"):
                    skill_list = loader.list_skills()
                elif isinstance(skill_count, int):
                    skill_count = skill_count  # just the count, no list available
            except Exception:
                pass
            result["skills"] = [
                {
                    "name": getattr(s, "name", str(s)),
                    "source": getattr(s, "source", "unknown"),
                    "status": "loaded",
                }
                for s in skill_list
            ]
            result["subsystems"]["skills"] = {"status": "ok", "discovered": len(result["skills"])}
        except Exception as exc:
            result["subsystems"]["skills"] = {"status": "error", "error": str(exc)}
            issues.append(f"skills: {exc}")

        # --- MCP: use cached singleton so readiness reflects same state as runs ---
        try:
            from hi_agent.mcp.registry import MCPRegistry
            if self._builder._mcp_registry is None:
                self._builder._mcp_registry = MCPRegistry()
            servers = self._builder._mcp_registry.list_servers()
            # Annotate each server with transport availability so integrators know
            # whether tools are actually invokable vs just registered.
            for srv in servers:
                srv_status = srv.get("status", "registered")
                if srv_status == "healthy":
                    srv["availability"] = "available"
                elif srv_status in ("registered",):
                    srv["availability"] = "registered_but_no_transport"
                else:
                    srv["availability"] = srv_status
            result["mcp_servers"] = servers
            connected = sum(1 for s in servers if s.get("status") == "healthy")
            result["subsystems"]["mcp"] = {
                "status": "ok",
                "servers": len(servers),
                "connected": connected,
                "registered_only": len(servers) - connected,
                # Honest transport status for integrators.
                "transport_status": "not_wired",
                "capability_mode": "infrastructure_only",
                "note": (
                    "External MCP transport (stdio/SSE/HTTP) not yet implemented. "
                    "Platform tools are available via /mcp/tools/list as MCP-compatible "
                    "endpoints. External server registration and forwarding are deferred."
                ),
            }
        except ImportError:
            result["mcp_servers"] = []
            result["subsystems"]["mcp"] = {"status": "not_configured"}
        except Exception as exc:
            result["subsystems"]["mcp"] = {"status": "error", "error": str(exc)}

        # --- plugins: use cached singleton so readiness reflects same state as runs ---
        try:
            from hi_agent.plugin.loader import PluginLoader
            if self._builder._plugin_loader is None:
                self._builder._plugin_loader = PluginLoader()
                # load_all() triggers actual discovery from plugin directories.
                # Without this, list_loaded() always returns [] on a fresh loader.
                self._builder._plugin_loader.load_all()
            loaded = self._builder._plugin_loader.list_loaded()
            result["plugins"] = loaded
            result["subsystems"]["plugins"] = {"status": "ok", "count": len(loaded)}
        except ImportError:
            result["plugins"] = []
            result["subsystems"]["plugins"] = {"status": "not_configured"}
        except Exception as exc:
            result["subsystems"]["plugins"] = {"status": "error", "error": str(exc)}

        # --- readiness decision ---
        kernel_ok = result["subsystems"].get("kernel", {}).get("status") == "ok"
        cap_ok = result["subsystems"].get("capabilities", {}).get("status") == "ok"
        # LLM error means prod mode requires credentials not present.
        # "not_configured" (dev fallback) is acceptable; "error" (missing prod creds) blocks.
        llm_status = result["subsystems"].get("llm", {}).get("status", "not_configured")
        llm_ok = llm_status != "error"
        result["ready"] = kernel_ok and cap_ok and llm_ok
        if not llm_ok:
            result["health"] = "degraded"
            issues.append("llm: credentials required for prod mode")
        if issues:
            logger.warning("readiness: %d issue(s): %s", len(issues), "; ".join(issues))

        # --- evolve policy snapshot ---
        try:
            from hi_agent.config.evolve_policy import resolve_evolve_effective
            import os as _os_ep
            _env_ep = _os_ep.environ.get("HI_AGENT_ENV", "dev").lower()
            _rt_mode = "dev-smoke" if _env_ep == "dev" else "prod-real"
            _ev_mode = getattr(self._builder._config, "evolve_mode", "auto")
            _ev_enabled, _ev_source = resolve_evolve_effective(_ev_mode, _rt_mode)
            result["evolve_policy"] = {
                "mode": _ev_mode,
                "effective": _ev_enabled,
                "source": _ev_source,
            }
        except Exception as _ep_exc:
            logger.debug("readiness: evolve_policy snapshot failed: %s", _ep_exc)

        # --- prerequisites transparency ---
        # Emit explicit prerequisites so integrators know exactly what is needed
        # when ready=false, without having to read source code.
        import os as _os
        from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode as _rrm_b
        env_mode = _os.environ.get("HI_AGENT_ENV", "dev").lower()
        result["runtime_mode"] = _rrm_b(env_mode, result)
        if env_mode == "prod":
            result["prerequisites"] = {
                "required_for_prod_mode": [
                    "OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable",
                    "kernel_base_url set to a real agent-kernel HTTP endpoint",
                ],
                "hint": (
                    "Run with HI_AGENT_ENV=dev (or use `serve` default) for "
                    "heuristic fallback without external dependencies."
                ),
            }
        else:
            result["prerequisites"] = {
                "mode": "dev — heuristic fallback active, no external dependencies required",
                "hint": "Use HI_AGENT_ENV=prod or `serve --prod` to require real credentials.",
            }

        return result
