#!/usr/bin/env bash
# Pre-commit hook: warn when hot-path files are staged without T3 evidence in commit message.
# Non-blocking — the blocking check is the CI t3-evidence-check job.

HOT_PATH_PATTERNS=(
  "hi_agent/llm/"
  "hi_agent/runtime/"
  "hi_agent/config/cognition_builder.py"
  "hi_agent/config/json_config_loader.py"
  "hi_agent/config/builder.py"
  "hi_agent/runner.py"
  "hi_agent/runner_stage.py"
  "hi_agent/runtime_adapter/"
  "hi_agent/memory/compressor.py"
  "hi_agent/server/app.py"
  "hi_agent/profiles/"
)

STAGED=$(git diff --cached --name-only)
COMMIT_MSG_FILE="$1"
COMMIT_MSG=""
if [ -f "$COMMIT_MSG_FILE" ]; then
  COMMIT_MSG=$(cat "$COMMIT_MSG_FILE")
fi

HOT_HIT=0
for pattern in "${HOT_PATH_PATTERNS[@]}"; do
  if echo "$STAGED" | grep -q "$pattern"; then
    HOT_HIT=1
    break
  fi
done

if [ "$HOT_HIT" -eq 1 ] && ! echo "$COMMIT_MSG" | grep -q "T3 evidence:"; then
  echo "WARNING: Hot-path files staged but no 'T3 evidence:' line in commit message."
  echo "  Add 'T3 evidence: docs/delivery/<YYYY-MM-DD>-<sha>-rule15-unified.json' OR"
  echo "  'T3 evidence: DEFERRED — <reason>' to the commit message."
  echo "  (This is a non-blocking warning. CI will enforce at PR time.)"
fi

exit 0
