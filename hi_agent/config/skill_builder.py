"""SkillBuilder: capability builder for skill subsystem.

Extracted from SystemBuilder in W6-003.
SystemBuilder.build_skill_* methods are now facades to SkillBuilder.
"""
from __future__ import annotations

import logging
from typing import Any

from hi_agent.config.trace_config import TraceConfig

logger = logging.getLogger(__name__)


class SkillBuilder:
    """Builds and caches skill subsystem components.

    Takes only TraceConfig — does not hold a reference to SystemBuilder.
    Singletons are cached internally.

    Can also be constructed without a config for workspace-aware skill loading:

        SkillBuilder(
            global_skill_dirs=["/path/to/global"],
            workspace_skill_dirs=["/path/to/workspace"],
        )

    In this mode, ``build()`` returns a flat list of :class:`SkillDefinition`
    objects.  Workspace skills take precedence over global ones on conflict
    (same skill_id).
    """

    def __init__(
        self,
        config: TraceConfig | None = None,
        *,
        global_skill_dirs: list[str] | None = None,
        workspace_skill_dirs: list[str] | None = None,
    ) -> None:
        self._config = config
        self._global_skill_dirs: list[str] = global_skill_dirs or []
        self._workspace_skill_dirs: list[str] = workspace_skill_dirs or []
        self._skill_loader: Any = None
        self._skill_evolver: Any = None

    def build(self) -> list[Any]:
        """Load skills from global and workspace directories; workspace wins on conflict.

        Returns:
            List of :class:`~hi_agent.skill.definition.SkillDefinition` objects.
            Skills from workspace_skill_dirs override global ones with the same
            skill_id.  Global skills are tagged ``source="global"``; workspace
            skills are tagged ``source="workspace"``.

        Skill ID resolution: when the SKILL.md file is the only file in a named
        subdirectory (e.g. ``lit-review/SKILL.md``), the directory name is used
        as the canonical skill_id so that workspace and global versions of the
        same directory name are correctly deduped.
        """
        import os as _os

        from hi_agent.skill.loader import SkillLoader

        skills_by_id: dict[str, Any] = {}

        def _load_dir_tagged(directory: str, source_tag: str) -> None:
            loader = SkillLoader()
            loaded = loader.load_dir(directory, source=source_tag)
            for skill in loaded:
                skill.source = source_tag
                # Re-key by parent directory name when the source file is SKILL.md.
                # This gives the natural skill_id (e.g. "lit-review") rather than
                # the generic filename-derived id ("skill").
                sp = getattr(skill, "source_path", "")
                if sp and _os.path.basename(sp) == "SKILL.md":
                    parent_name = _os.path.basename(_os.path.dirname(sp))
                    if parent_name and parent_name != _os.path.basename(directory):
                        skill.skill_id = parent_name.lower()
                skills_by_id[skill.skill_id] = skill

        # Load global dirs first (lower precedence).
        for d in self._global_skill_dirs:
            _load_dir_tagged(d, "global")

        # Load workspace dirs second — same skill_id overwrites global entry.
        for d in self._workspace_skill_dirs:
            _load_dir_tagged(d, "workspace")

        return list(skills_by_id.values())

    def build_skill_registry(self):
        """Build SkillRegistry using configured storage directory."""
        from hi_agent.skill.registry import SkillRegistry
        return SkillRegistry(storage_dir=self._config.skill_storage_dir)

    def build_skill_loader(self) -> Any:
        """Build or return the shared SkillLoader singleton.

        Search order (highest to lowest priority):
        1. Built-in skills bundled with hi-agent (hi_agent/skills/builtin/)
        2. User-global skills (~/.hi_agent/skills/)
        3. Project-local skills (config.skill_storage_dir, default .hi_agent/skills/)
        4. Workspace-specific skills (workspace_skill_dirs, highest priority)
        """
        if self._skill_loader is not None:
            return self._skill_loader
        import pathlib

        from hi_agent.skill.loader import SkillLoader

        if self._config is None:
            # Loader built without config: use explicit dirs only.
            self._skill_loader = SkillLoader(search_dirs=[])
            return self._skill_loader

        builtin_dir = str(pathlib.Path(__file__).parent.parent / "skills" / "builtin")
        user_global_dir = str(pathlib.Path.home() / ".hi_agent" / "skills")
        project_dir = self._config.skill_storage_dir

        seen: set[str] = set()
        dirs: list[str] = []
        for d in [builtin_dir, user_global_dir, project_dir]:
            if d not in seen:
                seen.add(d)
                dirs.append(d)

        # Append workspace dirs at the end (highest precedence in discover()).
        for d in self._workspace_skill_dirs:
            if d not in seen:
                seen.add(d)
                dirs.append(d)

        self._skill_loader = SkillLoader(
            search_dirs=dirs,
            max_skills_in_prompt=self._config.skill_loader_max_skills_in_prompt,
            max_prompt_tokens=self._config.skill_loader_max_prompt_tokens,
        )
        return self._skill_loader

    def build_skill_observer(self) -> Any:
        """Build SkillObserver for execution telemetry."""
        from hi_agent.skill.observer import SkillObserver
        return SkillObserver(
            storage_dir=self._config.skill_storage_dir + "/observations"
        )

    def build_skill_version_manager(self) -> Any:
        """Build SkillVersionManager for champion/challenger versioning."""
        from hi_agent.skill.version import SkillVersionManager
        mgr = SkillVersionManager(
            storage_dir=self._config.skill_storage_dir + "/versions"
        )
        try:
            mgr.load()
        except (FileNotFoundError, KeyError, ValueError):
            pass  # no prior state on first run — expected on fresh installs
        return mgr

    def build_skill_evolver(self, llm_gateway: Any = None) -> Any:
        """Build or return the shared SkillEvolver singleton.

        Cached so that the internal _runs_since_evolve counter persists across
        per-request RunExecutor instances; otherwise the interval counter resets
        to 0 on every request and evolve_cycle() never fires.
        """
        if self._skill_evolver is not None:
            return self._skill_evolver
        from hi_agent.skill.evolver import SkillEvolver
        observer = self.build_skill_observer()
        version_mgr = self.build_skill_version_manager()
        self._skill_evolver = SkillEvolver.from_config(
            cfg=self._config,
            llm_gateway=llm_gateway,
            observer=observer,
            version_manager=version_mgr,
        )
        return self._skill_evolver
