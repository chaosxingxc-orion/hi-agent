#!/usr/bin/env python3
"""Deprecated shim: use run_t3_gate.py --provider volces instead.

This script will be removed in Wave 24.
"""
import subprocess
import sys
import warnings

if __name__ == "__main__":
    warnings.warn(
        "rule15_volces_gate.py is deprecated; use run_t3_gate.py --provider volces instead. "
        "This shim will be removed in Wave 24.",
        DeprecationWarning,
        stacklevel=1,
    )

    # Forward all arguments to the new provider-neutral gate with --provider volces.
    result = subprocess.run(
        [sys.executable, "scripts/run_t3_gate.py", "--provider", "volces", *sys.argv[1:]],
        cwd=None,
    )
    sys.exit(result.returncode)
