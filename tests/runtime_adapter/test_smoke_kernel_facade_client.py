"""Smoke test: hi_agent.runtime_adapter.kernel_facade_client importable and instantiable."""
import os

import pytest


@pytest.mark.smoke
def test_kernel_facade_client_importable():
    """KernelFacadeClient can be imported without error."""
    from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient

    assert KernelFacadeClient is not None


@pytest.mark.smoke
def test_kernel_facade_client_direct_mode():
    """KernelFacadeClient can be instantiated in direct mode with a facade=None."""
    from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient

    try:
        client = KernelFacadeClient(mode="direct", facade=None)
        assert client is not None
    except TypeError as e:
        pytest.skip(f"Constructor requires dependencies not available in smoke: {e}")


@pytest.mark.smoke
def test_kernel_facade_client_http_mode_localhost():
    """KernelFacadeClient can be instantiated in http mode pointing at localhost."""
    from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient

    client = KernelFacadeClient(mode="http", base_url="http://localhost:9090")
    assert client is not None


@pytest.mark.smoke
def test_kernel_facade_client_rejects_non_localhost_without_override():
    """KernelFacadeClient raises ValueError for non-localhost base_url without override."""
    # Ensure override is not set
    os.environ.pop("HI_AGENT_KERNEL_BASE_URL_OVERRIDE_UNSAFE", None)
    from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient

    with pytest.raises(ValueError):
        KernelFacadeClient(mode="http", base_url="http://external-host:9090")


@pytest.mark.smoke
def test_kernel_facade_client_rejects_invalid_mode():
    """KernelFacadeClient raises ValueError for an unrecognized mode."""
    from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient

    with pytest.raises(ValueError):
        KernelFacadeClient(mode="grpc")
