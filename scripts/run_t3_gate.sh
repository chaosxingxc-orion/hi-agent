#!/bin/bash
# Provider-neutral T3 gate runner.
# Usage: bash scripts/run_t3_gate.sh [--provider {volces,anthropic,openai,auto}] --output <path> [...]
set -e
python scripts/run_t3_gate.py "$@"
