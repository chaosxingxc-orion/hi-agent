#!/usr/bin/env bash
# Operator convenience: runs the 5-scenario drill via PM2
# Prerequisites: pm2 installed (npm install -g pm2), VOLCES_API_KEY set
set -euo pipefail

if ! command -v pm2 &>/dev/null; then
  echo "ERROR: pm2 not found. Install with: npm install -g pm2"
  exit 1
fi

if [[ -z "${VOLCES_API_KEY:-}" ]]; then
  echo "ERROR: VOLCES_API_KEY not set"
  exit 1
fi

DATE=$(date +%F)
SHA=$(git rev-parse --short HEAD)
OUTPUT="docs/delivery/${DATE}-${SHA}-operator-drill-v2-real.json"

VOLCES_API_KEY="$VOLCES_API_KEY" pm2 start deploy/ecosystem.config.js
sleep 10  # let process stabilize

python scripts/run_operator_drill.py \
  --version 2 \
  --base-url http://127.0.0.1:8000 \
  --pm2-app hi-agent \
  --output "$OUTPUT"

pm2 stop hi-agent
echo "Drill complete. Output: $OUTPUT"
jq '[.scenarios[] | select(.provenance=="real_pm2")] | length' "$OUTPUT"
