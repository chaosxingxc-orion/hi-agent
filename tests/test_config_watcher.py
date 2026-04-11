# tests/test_config_watcher.py
import asyncio
import json
import pytest
from hi_agent.config.stack import ConfigStack
from hi_agent.config.watcher import ConfigFileWatcher


@pytest.mark.asyncio
async def test_watcher_detects_file_change(tmp_path):
    base = tmp_path / "config.json"
    base.write_text('{"server_port": 9000}')
    stack = ConfigStack(base_config_path=str(base))

    reload_events: list[dict] = []

    async def on_reload(new_cfg):
        reload_events.append({"port": new_cfg.server_port})

    watcher = ConfigFileWatcher(stack=stack, on_reload=on_reload, poll_interval_seconds=0.05)
    task = asyncio.create_task(watcher.start())

    await asyncio.sleep(0.1)
    base.write_text('{"server_port": 8888}')
    await asyncio.sleep(0.2)

    watcher.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(reload_events) >= 1
    assert reload_events[-1]["port"] == 8888


@pytest.mark.asyncio
async def test_watcher_does_not_reload_unchanged_file(tmp_path):
    base = tmp_path / "config.json"
    base.write_text('{"server_port": 9000}')
    stack = ConfigStack(base_config_path=str(base))

    reload_count = 0

    async def on_reload(new_cfg):
        nonlocal reload_count
        reload_count += 1

    watcher = ConfigFileWatcher(stack=stack, on_reload=on_reload, poll_interval_seconds=0.05)
    task = asyncio.create_task(watcher.start())
    await asyncio.sleep(0.3)  # no file change
    watcher.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert reload_count == 0


@pytest.mark.asyncio
async def test_watcher_no_path_does_nothing():
    stack = ConfigStack()  # no base_config_path
    called = False

    async def on_reload(new_cfg):
        nonlocal called
        called = True

    watcher = ConfigFileWatcher(stack=stack, on_reload=on_reload, poll_interval_seconds=0.05)
    task = asyncio.create_task(watcher.start())
    await asyncio.sleep(0.1)
    watcher.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert not called
