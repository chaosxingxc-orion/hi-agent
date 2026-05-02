"""Operator-facing diagnostic and gate tooling for hi_agent.

This package was renamed from ``hi_agent.ops`` to disambiguate it from
``hi_agent.operations`` (long-running distributed coordinator/op-store/poller
substrate). ``operator_tools`` holds doctor/diagnostics/release-gate helpers
that operators run on demand against a running deployment; ``operations``
holds the platform's durable distributed-operation backbone (the canonical
long-running machinery, 150+ in-package imports).

The legacy ``hi_agent.ops`` import path still works via a deprecation shim
and will be removed in Wave 34.
"""
