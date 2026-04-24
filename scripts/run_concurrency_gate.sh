#!/usr/bin/env bash
# run_concurrency_gate.sh — Rule 8 T3 gate: 20 concurrent POST /runs
# Usage: HI_AGENT_LLM_MODE=real bash scripts/run_concurrency_gate.sh
# Records results to docs/delivery/<date>-<sha>-concurrency-gate.md
#
# Pass criteria (all 20 runs must satisfy):
#   - state == "done"
#   - llm_fallback_count == 0
#   - finished_at is non-null

set -e

PORT="${HI_AGENT_PORT:-8080}"
BASE="http://127.0.0.1:${PORT}"
N=20
PASS=0
FAIL=0
RESULTS=()

echo "=== concurrency gate: $N concurrent runs against $BASE ==="

# Launch all runs in parallel (background curl jobs)
declare -a PIDS=()
declare -a OUTFILES=()

for i in $(seq 1 $N); do
    OUTFILE=$(mktemp)
    OUTFILES+=("$OUTFILE")
    curl -sf -X POST "$BASE/runs" \
        -H "Content-Type: application/json" \
        -H "Idempotency-Key: gate-run-$i-$(date +%s)" \
        -d "{\"goal\": \"Gate run $i: print hello\", \"profile_id\": \"gate-test\"}" \
        -o "$OUTFILE" &
    PIDS+=($!)
done

echo "Waiting for all $N run creations..."
for pid in "${PIDS[@]}"; do
    wait "$pid" || true
done

# Extract run_ids
declare -a RUN_IDS=()
for f in "${OUTFILES[@]}"; do
    RID=$(python3 -c "import json,sys; d=json.load(open('$f')); print(d.get('run_id',''))" 2>/dev/null || true)
    [ -n "$RID" ] && RUN_IDS+=("$RID")
    rm -f "$f"
done

echo "Created ${#RUN_IDS[@]} runs. Polling for completion (max 120s each)..."

for RID in "${RUN_IDS[@]}"; do
    DEADLINE=$((SECONDS + 120))
    STATE="unknown"
    while [ $SECONDS -lt $DEADLINE ]; do
        STATE=$(curl -sf "$BASE/runs/$RID" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('state',''))" 2>/dev/null || echo "")
        [ "$STATE" = "done" ] || [ "$STATE" = "failed" ] || [ "$STATE" = "cancelled" ] && break
        sleep 2
    done

    FALLBACK=$(curl -sf "$BASE/runs/$RID" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('metadata',{}).get('llm_fallback_count',0))" 2>/dev/null || echo "?")
    FINISHED=$(curl -sf "$BASE/runs/$RID" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('finished_at') or '')" 2>/dev/null || echo "")

    if [ "$STATE" = "done" ] && [ "$FALLBACK" = "0" ] && [ -n "$FINISHED" ]; then
        PASS=$((PASS + 1))
        RESULTS+=("PASS $RID state=$STATE fallback=$FALLBACK finished_at=$FINISHED")
    else
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL $RID state=$STATE fallback=$FALLBACK finished_at=${FINISHED:-null}")
    fi
done

# Write evidence file
DATE=$(date +%Y-%m-%d)
SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
EVIDENCE_FILE="docs/delivery/${DATE}-${SHA}-concurrency-gate.md"
mkdir -p docs/delivery

{
    echo "# T3 Concurrency Gate Evidence"
    echo ""
    echo "Date: $DATE"
    echo "SHA: $SHA"
    echo "Runs: $N"
    echo "Pass: $PASS | Fail: $FAIL"
    echo ""
    echo "## Results"
    for r in "${RESULTS[@]}"; do
        echo "- $r"
    done
} > "$EVIDENCE_FILE"

echo ""
echo "=== Gate results: $PASS/$N passed ==="
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""
echo "Evidence: $EVIDENCE_FILE"

[ $FAIL -eq 0 ] && exit 0 || exit 1
