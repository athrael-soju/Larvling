"""PostToolUseFailure hook — records tool failures as quality signals."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import (
    open_db,
    reconfigure_stdout,
    ensure_session,
    log,
)


def handle(data):
    session_id = data.get("session_id")
    if not session_id:
        return

    tool_name = data.get("tool_name", "unknown")

    with open_db() as conn:
        ensure_session(conn, session_id)
        sess = conn.execute(
            "SELECT quality_signals FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if sess:
            existing = {}
            if sess["quality_signals"]:
                try:
                    existing = json.loads(sess["quality_signals"])
                except (json.JSONDecodeError, TypeError):
                    pass
            existing["tool_failures"] = existing.get("tool_failures", 0) + 1
            failures_by_tool = existing.get("failures_by_tool", {})
            failures_by_tool[tool_name] = failures_by_tool.get(tool_name, 0) + 1
            existing["failures_by_tool"] = failures_by_tool
            conn.execute(
                "UPDATE sessions SET quality_signals = ? WHERE id = ?",
                (json.dumps(existing), session_id),
            )
        conn.commit()

    log(f"ToolFailure: session={session_id[:8]}, tool={tool_name}")


if __name__ == "__main__":
    if os.environ.get("LARVLING_INTERNAL"):
        sys.exit(0)
    reconfigure_stdout()
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception as e:
        log(f"stdin read failed: {e}")
        sys.exit(0)
    if not raw.strip():
        sys.exit(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log(f"JSON parse failed ({len(raw)} bytes): {e}")
        sys.exit(0)
    handle(data)
