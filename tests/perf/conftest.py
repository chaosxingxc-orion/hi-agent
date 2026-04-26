import pytest


def pytest_collection_modifyitems(items):
    """Auto-apply @pytest.mark.perf to all tests in the perf directory."""
    for item in items:
        if "tests/perf" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.perf)
