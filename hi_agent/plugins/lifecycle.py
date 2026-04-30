"""PluginLifecycle: on_load / on_activate / on_deactivate hooks."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

from hi_agent.plugins.manifest import PluginManifest

logger = logging.getLogger(__name__)


class PluginLifecycle:
    """Manages plugin lifecycle hooks: load, activate, deactivate.

    When a plugin has an entry_point, this class imports it and calls
    the standard lifecycle functions if they exist:
    - ``on_load(manifest, context)``
    - ``on_activate(manifest, context)``
    - ``on_deactivate(manifest, context)``
    """

    def __init__(self, context: dict[str, Any] | None = None) -> None:
        """Initialize with optional context dict passed to lifecycle hooks.

        Args:
            context: Optional platform context (registry, builder, etc.)
                passed to plugin lifecycle functions.
        """
        self._context = context or {}

    def on_load(self, manifest: PluginManifest) -> bool:
        """Call the plugin's on_load hook.

        Returns True if the hook succeeded or was not present.
        """
        return self._call_hook(manifest, "on_load")

    def on_activate(self, manifest: PluginManifest) -> bool:
        """Call the plugin's on_activate hook.

        Returns True if the hook succeeded or was not present.
        """
        return self._call_hook(manifest, "on_activate")

    def on_deactivate(self, manifest: PluginManifest) -> bool:
        """Call the plugin's on_deactivate hook.

        Returns True if the hook succeeded or was not present.
        """
        return self._call_hook(manifest, "on_deactivate")

    def _call_hook(self, manifest: PluginManifest, hook_name: str) -> bool:
        """Import entry_point and call the named hook function."""
        if not manifest.entry_point or not manifest.plugin_dir:
            return True  # No entry point — silently pass

        entry_path = Path(manifest.plugin_dir) / manifest.entry_point
        if not entry_path.exists():
            logger.warning(
                "PluginLifecycle.%s: entry_point %r not found for plugin %r",
                hook_name,
                str(entry_path),
                manifest.name,
            )
            return False

        try:
            spec = importlib.util.spec_from_file_location(
                f"hi_agent_plugin_{manifest.name}", entry_path
            )
            if spec is None or spec.loader is None:
                return False
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]  expiry_wave: Wave 26

            hook_fn = getattr(module, hook_name, None)
            if hook_fn is None:
                return True  # Hook not defined — silently pass
            hook_fn(manifest, self._context)
            logger.info(
                "PluginLifecycle.%s: hook succeeded for plugin %r", hook_name, manifest.name
            )
            return True
        except Exception as exc:
            logger.warning(
                "PluginLifecycle.%s: hook failed for plugin %r: %s",
                hook_name,
                manifest.name,
                exc,
            )
            manifest.status = "error"
            manifest.error = str(exc)
            return False
