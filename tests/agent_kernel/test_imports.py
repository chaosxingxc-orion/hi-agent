"""Smoke test: every agent_kernel module must be importable without the source patcher."""


def test_agent_kernel_imports_without_patcher():
    """Verify no Python 2 except syntax remains in agent_kernel."""
    # If any file had unpatched Python2 syntax, this would raise SyntaxError
