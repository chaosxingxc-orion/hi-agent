import pytest


def pytest_collection_modifyitems(items):
    """Auto-apply @pytest.mark.integration to all tests in the integration directory."""
    for item in items:
        if "tests/integration" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)
