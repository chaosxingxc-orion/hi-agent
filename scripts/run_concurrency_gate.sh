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
echo "=== Phase 1 results: $PASS/$N passed ==="
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""
echo "Evidence: $EVIDENCE_FILE"

# ---------------------------------------------------------------------------
# Phase 2 — Idempotent dedupe under contention
# Fire N2 concurrent POST /runs with the SAME Idempotency-Key.
# Assert: exactly 1 run created (all run_ids identical) and replays return 200.
# ---------------------------------------------------------------------------
N2=5
PHASE2_KEY="gate-dedupe-$(date +%s)"
echo ""
echo "=== PHASE 2 (idempotent dedupe contention): $N2 concurrent requests, key=$PHASE2_KEY ==="

declare -a P2_PIDS=()
declare -a P2_OUTFILES=()
declare -a P2_HTTPCODE_FILES=()

for i in $(seq 1 $N2); do
    OUTFILE=$(mktemp)
    CODEFILE=$(mktemp)
    P2_OUTFILES+=("$OUTFILE")
    P2_HTTPCODE_FILES+=("$CODEFILE")
    curl -sf -o "$OUTFILE" -w "%{http_code}" -X POST "$BASE/runs" \
        -H "Content-Type: application/json" \
        -H "Idempotency-Key: $PHASE2_KEY" \
        -d "{\"goal\": \"Phase2 dedupe test\", \"profile_id\": \"gate-test\"}" \
        > "$CODEFILE" 2>/dev/null &
    P2_PIDS+=($!)
done

echo "Waiting for $N2 concurrent idempotent requests..."
for pid in "${P2_PIDS[@]}"; do
    wait "$pid" || true
done

# Collect results
declare -a P2_RUN_IDS=()
declare -a P2_HTTP_CODES=()
for idx in "${!P2_OUTFILES[@]}"; do
    OUTFILE="${P2_OUTFILES[$idx]}"
    CODEFILE="${P2_HTTPCODE_FILES[$idx]}"
    CODE=$(cat "$CODEFILE" 2>/dev/null || echo "000")
    RID=$(python3 -c "import json,sys; d=json.load(open('$OUTFILE')); print(d.get('run_id',''))" 2>/dev/null || true)
    P2_HTTP_CODES+=("$CODE")
    [ -n "$RID" ] && P2_RUN_IDS+=("$RID")
    rm -f "$OUTFILE" "$CODEFILE"
done

# Distinct run_ids — should be exactly 1
DISTINCT_RUNS=$(printf '%s\n' "${P2_RUN_IDS[@]}" | sort -u | wc -l | tr -d ' ')
# Count 200 responses (replays)
COUNT_200=0
for CODE in "${P2_HTTP_CODES[@]}"; do
    [ "$CODE" = "200" ] && COUNT_200=$((COUNT_200 + 1))
done
# Count 201 responses (created)
COUNT_201=0
for CODE in "${P2_HTTP_CODES[@]}"; do
    [ "$CODE" = "201" ] && COUNT_201=$((COUNT_201 + 1))
done

echo "Distinct run_ids returned: $DISTINCT_RUNS (expected 1)"
echo "HTTP 201 (created): $COUNT_201, HTTP 200 (replayed): $COUNT_200"

PHASE2_OK=true
[ "$DISTINCT_RUNS" != "1" ] && PHASE2_OK=false
[ "$COUNT_201" -ne 1 ] && PHASE2_OK=false
[ "$COUNT_200" -ne $((N2 - 1)) ] && PHASE2_OK=false

if $PHASE2_OK; then
    echo "PHASE 2 (idempotent dedupe contention): PASS"
else
    echo "PHASE 2 (idempotent dedupe contention): FAIL"
    echo "  Expected: 1 distinct run_id, 1 HTTP 201, $((N2 - 1)) HTTP 200"
    echo "  Got: $DISTINCT_RUNS distinct ids, $COUNT_201 x 201, $COUNT_200 x 200"
fi

# Append Phase 2 evidence to the same file
{
    echo ""
    echo "## Phase 2 — Idempotent Dedupe Contention"
    echo ""
    echo "Key: $PHASE2_KEY"
    echo "Concurrent requests: $N2"
    echo "Distinct run_ids: $DISTINCT_RUNS (expected 1)"
    echo "HTTP 201 (created): $COUNT_201"
    echo "HTTP 200 (replayed): $COUNT_200"
    if $PHASE2_OK; then
        echo "Result: PASS"
    else
        echo "Result: FAIL"
    fi
} >> "$EVIDENCE_FILE"

echo ""
echo "Evidence: $EVIDENCE_FILE"

# Exit non-zero if Phase 1 or Phase 2 failed.
{ [ $FAIL -eq 0 ] && $PHASE2_OK; } && exit 0 || exit 1
