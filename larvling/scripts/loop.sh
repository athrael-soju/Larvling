#!/bin/bash
# Larvling Loop - Ralph-style iteration with fresh context per cycle.
# Progress persists via Larvling's fact store.
# Each run gets a unique ID stored in .claude/larvling-loop-run.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUERY_PY="$SCRIPT_DIR/query.py"
QUERY="python \"$QUERY_PY\""
RUN_FILE=".claude/larvling-loop-run"

# --- Helpers ---

get_run_id() {
  if [ -f "$RUN_FILE" ]; then
    cat "$RUN_FILE"
  else
    echo ""
  fi
}

# --- Subcommands ---

do_cancel() {
  local RUN_ID
  RUN_ID=$(get_run_id)
  if [ -z "$RUN_ID" ]; then
    echo "No active loop."
    return
  fi
  python "$QUERY_PY" "DELETE FROM facts WHERE source = 'loop-$RUN_ID'"
  rm -f "$RUN_FILE"
  echo "Loop $RUN_ID cancelled. All loop facts cleared."
}

do_status() {
  local RUN_ID
  RUN_ID=$(get_run_id)
  if [ -z "$RUN_ID" ]; then
    echo "No active loop."
    return
  fi
  echo "Loop run: $RUN_ID"
  echo ""
  python "$QUERY_PY" "SELECT id, claim, notes AS status FROM facts WHERE source = 'loop-$RUN_ID' ORDER BY id"
}

do_start() {
  local MAX_ITERATIONS=10
  local ARGS=()

  while [[ $# -gt 0 ]]; do
    case $1 in
      --max-iterations)
        MAX_ITERATIONS="$2"
        shift 2
        ;;
      *)
        ARGS+=("$1")
        shift
        ;;
    esac
  done

  local PROMPT="${ARGS[*]}"
  if [ -z "$PROMPT" ]; then
    echo "Error: prompt is required" >&2
    exit 1
  fi

  # Check for existing active loop
  local EXISTING
  EXISTING=$(get_run_id)
  if [ -n "$EXISTING" ]; then
    echo "Error: Loop $EXISTING is already active." >&2
    echo "Use '/loop cancel' to cancel it first, or '/loop status' to check progress." >&2
    exit 1
  fi

  # Generate run ID and persist it
  local RUN_ID
  RUN_ID=$(date +%s)
  echo "$RUN_ID" > "$RUN_FILE"
  local SRC="loop-$RUN_ID"

  echo "Starting loop $RUN_ID — max $MAX_ITERATIONS iterations"
  echo "Task: $PROMPT"
  echo ""

  # Suppress Larvling hooks inside loop agents (loop manages its own state)
  export LARVLING_AGENT=1

  for i in $(seq 1 "$MAX_ITERATIONS"); do
    echo "==============================================================="
    echo "  Iteration $i / $MAX_ITERATIONS  (run $RUN_ID)"
    echo "==============================================================="

    # After first iteration, check if all stories are done
    if [ "$i" -gt 1 ]; then
      PENDING=$(python "$QUERY_PY" "SELECT COUNT(*) FROM facts WHERE source = '$SRC' AND tags LIKE '%story%' AND notes != 'done'" 2>/dev/null || echo "")
      if echo "$PENDING" | grep -q "| 0"; then
        echo ""
        echo "All stories complete at iteration $i."
        rm -f "$RUN_FILE"
        exit 0
      fi
    fi

    claude -p "You are a Larvling loop worker (iteration $i/$MAX_ITERATIONS, run $RUN_ID).

## Task
$PROMPT

## State — read first
Run: $QUERY \"SELECT id, claim, notes AS status FROM facts WHERE source = '$SRC' ORDER BY id\"

## Protocol

All facts for this loop use: source='$SRC'. Status lives in the 'notes' field (not in claim text).

### If NO stories exist yet (first iteration):
Decompose the task into discrete stories. Insert each:
$QUERY \"INSERT INTO facts (id, claim, domain, tags, notes, source) VALUES ('$SRC-001', '<story description>', 'loop', 'loop,story', 'pending', '$SRC')\"
Number sequentially: $SRC-001, $SRC-002, etc.
Then pick the first story and start implementing.

### If stories exist:
Pick the highest-priority story where notes='pending' and implement it.

### After completing a story:
$QUERY \"UPDATE facts SET notes = 'done' WHERE id = '<story_id>'\"

### Record learnings for future iterations:
$QUERY \"INSERT INTO facts (id, claim, domain, tags, notes, source) VALUES ('$SRC-L$i-a', '<insight>', 'loop', 'loop,learning', NULL, '$SRC')\"
Use $SRC-L$i-a, $SRC-L$i-b, etc. for multiple learnings per iteration.

### If blocked:
$QUERY \"UPDATE facts SET notes = 'blocked' WHERE id = '<story_id>'\"
$QUERY \"INSERT INTO facts (id, claim, domain, tags, notes, source) VALUES ('$SRC-B$i', '<why blocked>', 'loop', 'loop,blocker', NULL, '$SRC')\"
Then move to the next pending story.

### Parallel sub-work:
If a story benefits from parallelism, use TeamCreate + Task tool to spawn workers.
Workers read/write facts with source='$SRC' for shared context.

## Rules
- ONE story per iteration
- NEVER commit changes — the user commits when ready
- Read loop facts before starting — they are your memory
- Write learnings when done — they are the next iteration's memory" \
      --dangerously-skip-permissions \
      --max-turns 30 || true

    echo ""
    echo "--- Iteration $i complete ---"
    echo ""
    sleep 2
  done

  echo "Reached max iterations ($MAX_ITERATIONS)."
  do_status
  exit 1
}

# --- Main ---

case "${1:-}" in
  cancel) do_cancel ;;
  status) do_status ;;
  "")
    echo "Usage: loop.sh <prompt> [--max-iterations N]" >&2
    echo "       loop.sh cancel" >&2
    echo "       loop.sh status" >&2
    exit 1
    ;;
  *) do_start "$@" ;;
esac
