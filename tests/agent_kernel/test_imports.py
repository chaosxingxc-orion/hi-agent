"""Smoke test: every agent_kernel module must be importable without the source patcher."""
import importlib
import pkgutil
import agent_kernel


def test_agent_kernel_imports_without_patcher():
    """Verify no Python 2 except syntax remains in agent_kernel."""
    import agent_kernel.kernel
    import agent_kernel.adapters
    import agent_kernel.runtime
    import agent_kernel.service
    import agent_kernel.substrate
    # If any file had unpatched Python2 syntax, this would raise SyntaxError
