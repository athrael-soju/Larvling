#!/bin/bash
# Larvling Loop - Ralph-style iteration with fresh context per cycle.
# Progress persists via Larvling's fact store (domain=loop).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUERY_PY="$SCRIPT_DIR/query.py"
QUERY="python \"$QUERY_PY\""

# --- Subcommands ---

do_cancel() {
  python "$QUERY_PY" "DELETE FROM facts WHERE domain = 'loop'"
  echo "Loop cancelled. All loop facts cleared."
}

do_status() {
  python "$QUERY_PY" "SELECT id, claim FROM facts WHERE domain = 'loop' ORDER BY id"
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

  echo "Starting loop — max $MAX_ITERATIONS iterations"
  echo "Task: $PROMPT"
  echo ""

  # Suppress Larvling hooks inside loop agents (loop manages its own state)
  export LARVLING_AGENT=1

  for i in $(seq 1 "$MAX_ITERATIONS"); do
    echo "==============================================================="
    echo "  Iteration $i / $MAX_ITERATIONS"
    echo "==============================================================="

    # After first iteration, check if all stories are done
    if [ "$i" -gt 1 ]; then
      PENDING=$(python "$QUERY_PY" "SELECT COUNT(*) FROM facts WHERE domain = 'loop' AND tags LIKE '%story%' AND claim NOT LIKE '%done%'" 2>/dev/null || echo "")
      if echo "$PENDING" | grep -q "| 0"; then
        echo ""
        echo "All stories complete at iteration $i."
        exit 0
      fi
    fi

    claude -p "You are a Larvling loop worker (iteration $i/$MAX_ITERATIONS).

## Task
$PROMPT

## State — read first
Run: $QUERY \"SELECT id, claim FROM facts WHERE domain = 'loop' ORDER BY id\"

## Protocol
- If NO stories exist yet, decompose the task into discrete stories. Insert each:
  $QUERY \"INSERT INTO facts (id, claim, domain, tags, source) VALUES ('L-NNN', 'Story: <desc> | Status: pending', 'loop', 'loop,story', 'loop')\"
  Then pick the first story and start implementing.

- If stories exist, pick the highest-priority one with status 'pending' and implement it.

- After completing a story, update its status:
  $QUERY \"UPDATE facts SET claim = replace(claim, 'pending', 'done') WHERE id = 'L-NNN'\"

- Record learnings for future iterations:
  $QUERY \"INSERT INTO facts (id, claim, domain, tags, source) VALUES ('L-NNN-learn', '<insight>', 'loop', 'loop,learning', 'loop')\"

- If a story needs parallel sub-work, use TeamCreate + Task tool to spawn workers.
  Workers can read/write loop facts for shared context.

## Rules
- ONE story per iteration
- NEVER commit changes — the user commits when ready
- Read loop facts before starting — they are your memory
- Write learnings when done — they are the next iteration's memory
- If blocked, record a blocker fact and move on" \
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
