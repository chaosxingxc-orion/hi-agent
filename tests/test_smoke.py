"""Smoke tests for dependency and package imports."""

from hi_agent import contracts


def test_contracts_package_importable() -> None:
    """Contracts package should be importable and expose deterministic_id."""
    assert hasattr(contracts, "deterministic_id")


def test_key_subsystems_importable() -> None:
    """Core subsystems should import without side effects."""
    import hi_agent.capability as capability
    import hi_agent.events as events
    import hi_agent.management as management
    import hi_agent.memory as memory

    assert capability is not None
    assert events is not None
    assert management is not None
    assert memory is not None
