# hi_agent/config/watcher.py
"""Async file watcher for ConfigStack hot-reload.

Polls config files every *poll_interval_seconds*.  When mtime changes,
calls ``stack.invalidate()`` then invokes the ``on_reload`` callback with
the freshly resolved config.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class ConfigFileWatcher:
    """Periodically checks config file mtime and triggers reload on change."""

    def __init__(
        self,
        stack: Any,  # ConfigStack — avoid circular import at module level
        on_reload: Callable[..., Awaitable[None]],
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self._stack = stack
        self._on_reload = on_reload
        self._poll_interval = poll_interval_seconds
        self._running = False
        self._last_mtimes: dict[str, float] = {}

    def stop(self) -> None:
        """Signal the watcher loop to stop."""
        self._running = False

    async def start(self) -> None:
        """Run the polling loop until ``stop()`` is called."""
        if not self._stack._base_path:
            return  # nothing to watch

        self._running = True
        # Snapshot initial mtimes
        self._last_mtimes = self._current_mtimes()

        while self._running:
            await asyncio.sleep(self._poll_interval)
            current = self._current_mtimes()
            if current != self._last_mtimes:
                self._last_mtimes = current
                self._stack.invalidate()
                try:
                    new_cfg = self._stack.resolve()
                    await self._on_reload(new_cfg)
                    logger.info("Config reloaded from %s", self._stack._base_path)
                except Exception as exc:
                    logger.error("Config reload failed: %s", exc)

    def _current_mtimes(self) -> dict[str, float]:
        """Return a dict of {path: mtime} for all watched paths."""
        paths = self._watched_paths()
        mtimes: dict[str, float] = {}
        for p in paths:
            try:
                mtimes[p] = os.path.getmtime(p)
            except FileNotFoundError:
                mtimes[p] = 0.0
        return mtimes

    def _watched_paths(self) -> list[str]:
        paths = []
        if self._stack._base_path:
            paths.append(self._stack._base_path)
        if self._stack._profile:
            from hi_agent.config.profile import profile_path_for
            p = profile_path_for(self._stack._base_path, self._stack._profile)
            if p:
                paths.append(p)
        return paths
