#!/usr/bin/env bash
# dev_smoke.sh — Rule 3 pre-commit smoke check
# Usage: bash scripts/dev_smoke.sh
# Pass criteria: ruff clean + import clean + /health 200 within 3s

set -e

echo "=== [1/3] ruff check ==="
python -m ruff check .

echo "=== [2/3] import check ==="
python -c "import hi_agent; import agent_kernel; print('imports OK')"

echo "=== [3/3] health endpoint ==="
python -m hi_agent serve --port 8081 &
SERVER_PID=$!
sleep 3

STATUS=$(curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1:8081/health 2>/dev/null || echo "000")
kill "$SERVER_PID" 2>/dev/null || true

if [ "$STATUS" = "200" ]; then
    echo "health OK (200)"
else
    echo "health FAILED (got $STATUS)" >&2
    exit 1
fi

echo "=== smoke PASSED ==="
