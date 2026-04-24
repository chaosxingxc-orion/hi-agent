"""Smoke test: hi_agent.runtime_adapter.event_buffer importable and instantiable."""
import pytest


@pytest.mark.smoke
def test_event_buffer_importable():
    """EventBuffer can be imported without error."""
    from hi_agent.runtime_adapter.event_buffer import EventBuffer

    assert EventBuffer is not None


@pytest.mark.smoke
def test_event_buffer_basic_instantiation():
    """EventBuffer can be instantiated with default args."""
    from hi_agent.runtime_adapter.event_buffer import EventBuffer

    buf = EventBuffer()
    assert buf is not None


@pytest.mark.smoke
def test_event_buffer_custom_max_size():
    """EventBuffer can be instantiated with a custom max_size."""
    from hi_agent.runtime_adapter.event_buffer import EventBuffer

    buf = EventBuffer(max_size=100)
    assert buf is not None


@pytest.mark.smoke
def test_event_buffer_append_and_size():
    """EventBuffer accepts appended events and reports size."""
    from hi_agent.runtime_adapter.event_buffer import EventBuffer

    buf = EventBuffer(max_size=10)
    buf.append("stage_opened", {"run_id": "r1", "stage_id": "s1"})
    assert buf.size() >= 1


@pytest.mark.smoke
def test_event_buffer_rejects_invalid_max_size():
    """EventBuffer raises ValueError for max_size < 1."""
    from hi_agent.runtime_adapter.event_buffer import EventBuffer

    with pytest.raises(ValueError):
        EventBuffer(max_size=0)
