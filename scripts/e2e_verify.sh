#!/usr/bin/env bash
# hi-agent downstream end-to-end verification script
# Usage: bash scripts/e2e_verify.sh [API_BASE]
# Example: bash scripts/e2e_verify.sh http://127.0.0.1:8080

set -euo pipefail

API=${1:-http://127.0.0.1:8080}
PASS=0
FAIL=0

pass() { echo "[PASS] $1"; PASS=$((PASS+1)); }
fail() { echo "[FAIL] $1"; FAIL=$((FAIL+1)); }
info() { echo "[INFO] $1"; }

echo "========================================"
echo "hi-agent E2E Verification"
echo "Target: $API"
echo "========================================"

echo ""
echo "=== Step 1: Readiness check ==="
READY=$(curl -sf "$API/ready") || { fail "GET /ready unreachable"; exit 1; }
echo "$READY" | jq '{runtime_mode, execution_mode}'
RUNTIME_MODE=$(echo "$READY" | jq -r '.runtime_mode // "unknown"')

if [ "$RUNTIME_MODE" = "local-real" ] || [ "$RUNTIME_MODE" = "prod-real" ]; then
  pass "runtime_mode=$RUNTIME_MODE (real LLM active)"
else
  info "runtime_mode=$RUNTIME_MODE (heuristic mode; set LLM env vars for local-real)"
fi

echo ""
echo "=== Step 2: Sequential run creation (unique run_id check) ==="
declare -a RUN_IDS=()
for i in 1 2 3; do
  RESP=$(curl -sf -X POST "$API/runs" \
    -H 'Content-Type: application/json' \
    -d "{\"goal\":\"smoke $i\",\"task_family\":\"quick_task\",\"risk_level\":\"low\"}")
  RID=$(echo "$RESP" | jq -r '.run_id // empty')
  if [ -z "$RID" ]; then
    fail "POST /runs smoke $i: no run_id in response"
  else
    RUN_IDS+=("$RID")
    echo "$RESP" | jq -c '{run_id, state}'
  fi
done

UNIQUE_COUNT=$(printf '%s\n' "${RUN_IDS[@]}" | sort -u | wc -l)
if [ "$UNIQUE_COUNT" -eq 3 ]; then
  pass "3 distinct run_ids created"
else
  fail "Duplicate run_ids detected (got $UNIQUE_COUNT unique of 3)"
fi

echo ""
echo "=== Step 3: Run-to-terminal (wait up to 60s) ==="
FINAL_RUN=$(curl -sf -X POST "$API/runs" \
  -H 'Content-Type: application/json' \
  -d '{"goal":"Verify end-to-end execution pipeline","task_family":"quick_task","risk_level":"low"}' \
  | jq -r '.run_id // empty')

if [ -z "$FINAL_RUN" ]; then
  fail "POST /runs for final run: no run_id"
else
  info "Tracking run: $FINAL_RUN"
  TERMINAL=false
  for i in $(seq 1 30); do
    RESP=$(curl -sf "$API/runs/$FINAL_RUN")
    STATE=$(echo "$RESP" | jq -r '.state // "unknown"')
    STAGE=$(echo "$RESP" | jq -r '.current_stage // "-"')
    printf "[%2d] state=%-12s current_stage=%s\n" "$i" "$STATE" "$STAGE"
    if [ "$STATE" = "completed" ] || [ "$STATE" = "failed" ]; then
      TERMINAL=true
      pass "Run reached terminal state: $STATE"
      break
    fi
    sleep 2
  done
  if [ "$TERMINAL" = false ]; then
    fail "Run did not reach terminal state within 60s"
  fi
fi

echo ""
echo "=== Step 4: GET /runs/{id} observable fields ==="
DETAIL=$(curl -sf "$API/runs/$FINAL_RUN")
CURRENT_STAGE=$(echo "$DETAIL" | jq -r '.current_stage // null')
STAGE_UPDATED=$(echo "$DETAIL" | jq -r '.stage_updated_at // null')
echo "$DETAIL" | jq '{state, current_stage, stage_updated_at, updated_at}'

if [ "$CURRENT_STAGE" != "null" ]; then
  pass "current_stage field present: $CURRENT_STAGE"
else
  fail "current_stage field missing or null"
fi

echo ""
echo "========================================"
echo "Result: $PASS passed, $FAIL failed"
echo "========================================"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
