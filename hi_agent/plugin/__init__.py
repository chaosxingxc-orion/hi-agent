"""Plugin system for hi-agent.

Plugins extend hi-agent's capabilities beyond built-in defaults.  Each
plugin declares a manifest describing what it provides and hooks into the
platform lifecycle.

Plugin types:
- capability plugins: register new CapabilitySpec entries
- skill plugins: add SKILL.md definitions to the skill loader search path
- MCP plugins: register new MCP server connections

Usage::

    # In a plugin directory, create plugin.json:
    # {"name": "my-plugin", "version": "1.0.0", "type": "capability", ...}

    # Then register the directory:
    from hi_agent.plugin.loader import PluginLoader
    loader = PluginLoader(plugin_dirs=["./plugins"])
    loader.load_all()
"""

from hi_agent.plugin.manifest import PluginManifest
from hi_agent.plugin.loader import PluginLoader
from hi_agent.plugin.lifecycle import PluginLifecycle

__all__ = ["PluginManifest", "PluginLoader", "PluginLifecycle"]
