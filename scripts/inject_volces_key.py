#!/usr/bin/env python3
"""Deprecated shim: use inject_provider_key.py --provider volces instead.

This script will be removed in Wave 15.
"""
import subprocess
import sys
import warnings

warnings.warn(
    "inject_volces_key.py is deprecated; use inject_provider_key.py --provider volces instead. "
    "This shim will be removed in Wave 15.",
    DeprecationWarning,
    stacklevel=1,
)

# Forward all arguments to the new script with --provider volces
result = subprocess.run(
    [sys.executable, "scripts/inject_provider_key.py", "--provider", "volces", *sys.argv[1:]],
    cwd=None,
)
sys.exit(result.returncode)
