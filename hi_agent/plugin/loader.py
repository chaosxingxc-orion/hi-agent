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

    def list_loaded(self) -> list[dict[str, Any]]:
        """Return serializable list of loaded plugin manifests."""
        return [m.to_dict() for m in self._loaded.values()]

    def get(self, name: str) -> PluginManifest | None:
        """Get a loaded plugin by name."""
        return self._loaded.get(name)

    def __len__(self) -> int:
        """Return number of loaded plugins."""
        return len(self._loaded)
