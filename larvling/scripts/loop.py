"""
Larvling Loop - iteration loop lifecycle management.

Subcommands: start, cancel, status
"""

import sys

from db import (
    open_db,
    require_db,
    reconfigure_stdout,
    create_loop,
    get_any_active_loop,
    end_loop,
)


def cmd_start(args):
    """Start a new iteration loop."""
    prompt = None
    max_iterations = 0
    completion_promise = None

    i = 0
    positional = []
    while i < len(args):
        if args[i] == "--max-iterations" and i + 1 < len(args):
            try:
                max_iterations = int(args[i + 1])
                if max_iterations < 0:
                    raise ValueError
            except ValueError:
                print("Error: --max-iterations must be a non-negative number", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == "--completion-promise" and i + 1 < len(args):
            completion_promise = args[i + 1]
            i += 2
        else:
            positional.append(args[i])
            i += 1

    prompt = " ".join(positional).strip() if positional else None
    if not prompt:
        print("Error: prompt is required", file=sys.stderr)
        sys.exit(1)

    with open_db() as conn:
        # Check for existing active loop
        existing = get_any_active_loop(conn)
        if existing:
            print(f"Error: An active loop already exists (id={existing['id']}, "
                  f"session={existing['session_id'][:8]}, "
                  f"iteration={existing['iteration']})")
            print("Use /cancel-loop to cancel it first.")
            sys.exit(1)

        # Get the most recent session
        row = conn.execute(
            "SELECT id FROM sessions ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            print("Error: No active session found", file=sys.stderr)
            sys.exit(1)

        session_id = row["id"]
        loop_id = create_loop(conn, session_id, prompt, max_iterations, completion_promise)
        conn.commit()

    # Print setup message
    iter_str = f" (max {max_iterations} iterations)" if max_iterations > 0 else " (unlimited iterations)"
    promise_str = f"\n**Completion promise:** `{completion_promise}`" if completion_promise else ""

    print(f"# Loop Started (id={loop_id}){iter_str}")
    print(f"\n**Prompt:** {prompt}{promise_str}")
    print()
    print("## Rules")
    print("- Do NOT output a false completion promise. The promise tag must reflect genuine task completion.")
    print("- Each iteration, review your previous work in files and git before continuing.")
    print("- Focus on making measurable progress each iteration.")
    if completion_promise:
        print(f"- When the task is genuinely complete, output: `<promise>{completion_promise}</promise>`")
    print()
    print(f"Begin working on: **{prompt}**")


def cmd_cancel(args):
    """Cancel the active loop."""
    with open_db() as conn:
        loop = get_any_active_loop(conn)
        if not loop:
            print("No active loop to cancel.")
            return

        changes_before = conn.total_changes
        end_loop(conn, loop["id"], "cancelled")
        if conn.total_changes == changes_before:
            # Loop was already ended (race with Stop hook)
            print(f"Loop {loop['id']} was already finished (possibly by the Stop hook).")
            return
        conn.commit()
        print(f"Loop cancelled (id={loop['id']}, completed {loop['iteration']} iterations)")


def cmd_status(args):
    """Show current loop status."""
    with open_db() as conn:
        loop = get_any_active_loop(conn)
        if not loop:
            print("No active loop.")
            return

        iter_str = (f"{loop['iteration']}/{loop['max_iterations']}"
                    if loop["max_iterations"] > 0 else str(loop["iteration"]))
        print(f"**Active Loop** (id={loop['id']})")
        print(f"- Session: {loop['session_id'][:8]}")
        print(f"- Iteration: {iter_str}")
        print(f"- Started: {loop['started_at']}")
        print(f"- Prompt: {loop['prompt']}")
        if loop["completion_promise"]:
            print(f"- Completion promise: {loop['completion_promise']}")


def main():
    require_db()
    reconfigure_stdout()

    args = sys.argv[1:]
    if not args:
        print("Usage: loop.py <start|cancel|status> [args...]", file=sys.stderr)
        sys.exit(1)

    cmd = args[0]
    rest = args[1:]

    if cmd == "start":
        cmd_start(rest)
    elif cmd == "cancel":
        cmd_cancel(rest)
    elif cmd == "status":
        cmd_status(rest)
    else:
        print(f"Unknown subcommand: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
