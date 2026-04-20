"""Tests for RetrievalEngine lifecycle methods (E-3)."""
from __future__ import annotations

import inspect
import tempfile

import pytest
from hi_agent.knowledge.retrieval_engine import RetrievalEngine


def test_warm_index_async_exists_and_is_callable() -> None:
    """warm_index_async must exist and be a coroutine function."""
    assert inspect.iscoroutinefunction(RetrievalEngine.warm_index_async)


def test_mark_index_dirty_sets_dirty_flag() -> None:
    """mark_index_dirty must set _index_dirty to True."""
    with tempfile.TemporaryDirectory() as d:
        engine = RetrievalEngine(storage_dir=d)
        # Initially _index_dirty is True; call build_index to clear it.
        engine.build_index()
        assert engine._index_dirty is False
        engine.mark_index_dirty()
        assert engine._index_dirty is True


def test_mark_index_dirty_clears_indexed_flag() -> None:
    """mark_index_dirty must also reset _indexed so next retrieve rebuilds."""
    with tempfile.TemporaryDirectory() as d:
        engine = RetrievalEngine(storage_dir=d)
        engine.build_index()
        assert engine._indexed is True
        engine.mark_index_dirty()
        assert engine._indexed is False


@pytest.mark.asyncio
async def test_warm_index_async_returns_int() -> None:
    """warm_index_async must return an int (doc count)."""
    with tempfile.TemporaryDirectory() as d:
        engine = RetrievalEngine(storage_dir=d)
        result = await engine.warm_index_async()
        assert isinstance(result, int)
        assert result >= 0
