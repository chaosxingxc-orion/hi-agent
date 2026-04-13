"""PluginLoader: discover and load plugins from directories."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hi_agent.plugin.manifest import PluginManifest

logger = logging.getLogger(__name__)

_MANIFEST_FILENAMES = ("plugin.json", "plugin.yaml", "PLUGIN.md")


class PluginLoader:
    """Discover and load hi-agent plugins from directories.

    Searches for plugin.json files in the configured plugin directories
    and loads their manifests.  Does not execute plugin code by default
    — call ``activate()`` or ``activate_all()`` to run lifecycle hooks.
    """

    def __init__(self, plugin_dirs: list[str] | None = None) -> None:
        """Initialize with optional list of directories to search.

        Args:
            plugin_dirs: Directories to search for plugins. Defaults to
                [".hi_agent/plugins", "~/.hi_agent/plugins"].
        """
        if plugin_dirs is None:
            home_dir = str(Path.home() / ".hi_agent" / "plugins")
            plugin_dirs = [".hi_agent/plugins", home_dir]
        self._plugin_dirs = plugin_dirs
        self._loaded: dict[str, PluginManifest] = {}

    def load_all(self) -> list[PluginManifest]:
        """Discover and load all plugins from configured directories.

        Returns:
            List of successfully loaded PluginManifest instances.
        """
        loaded: list[PluginManifest] = []
        for plugin_dir in self._plugin_dirs:
            p = Path(plugin_dir)
            if not p.exists():
                logger.debug("PluginLoader: directory %r does not exist, skipping.", plugin_dir)
                continue
            # Each subdirectory is a candidate plugin
            for subdir in p.iterdir():
                if subdir.is_dir():
                    manifest = self._try_load(subdir)
                    if manifest is not None:
                        self._loaded[manifest.name] = manifest
                        loaded.append(manifest)
                        logger.info(
                            "PluginLoader: loaded plugin %r v%s from %s",
                            manifest.name,
                            manifest.version,
                            subdir,
                        )
        return loaded

    def _try_load(self, plugin_dir: Path) -> PluginManifest | None:
        """Try to load a plugin from a directory."""
        for fname in _MANIFEST_FILENAMES:
            manifest_path = plugin_dir / fname
            if manifest_path.exists():
                try:
                    return PluginManifest.from_json(manifest_path)
                except Exception as exc:
                    logger.warning(
                        "PluginLoader: failed to load manifest at %s: %s", manifest_path, exc
                    )
        return None

    def activate(
        self,
        name: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Activate a single plugin by name, running its lifecycle hooks.

        Args:
            name: Name of the plugin to activate (must be loaded first).
            context: Optional platform context dict passed to plugin hooks
                (e.g. capability registry, builder).

        Returns:
            True if the plugin was successfully activated, False otherwise.
        """
        manifest = self._loaded.get(name)
        if manifest is None:
            logger.warning("PluginLoader.activate: plugin %r is not loaded.", name)
            return False
        from hi_agent.plugin.lifecycle import PluginLifecycle
        lifecycle = PluginLifecycle(context=context)
        if lifecycle.on_load(manifest) and lifecycle.on_activate(manifest):
            manifest.status = "active"
            logger.info("PluginLoader.activate: plugin %r is now active.", name)
            return True
        return False

    def activate_all(
        self,
        context: dict[str, Any] | None = None,
    ) -> int:
        """Activate all loaded plugins, running their lifecycle hooks.

        Args:
            context: Optional platform context dict passed to each plugin's
                lifecycle hooks (e.g. capability registry, builder).

        Returns:
            Number of plugins successfully activated.
        """
        from hi_agent.plugin.lifecycle import PluginLifecycle
        lifecycle = PluginLifecycle(context=context)
        activated = 0
        for manifest in list(self._loaded.values()):
            if lifecycle.on_load(manifest) and lifecycle.on_activate(manifest):
                manifest.status = "active"
                activated += 1
                logger.info(
                    "PluginLoader.activate_all: plugin %r is now active.", manifest.name
                )
        return activated

    def list_loaded(self) -> list[dict[str, Any]]:
        """Return serializable list of loaded plugin manifests."""
        return [m.to_dict() for m in self._loaded.values()]

    def get(self, name: str) -> PluginManifest | None:
        """Get a loaded plugin by name."""
        return self._loaded.get(name)

    def __len__(self) -> int:
        """Return number of loaded plugins."""
        return len(self._loaded)
