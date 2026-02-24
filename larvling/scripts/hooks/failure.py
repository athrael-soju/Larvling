"""PostToolUseFailure hook — records tool failures as quality signals."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import (
    open_db,
    ensure_session,
    accumulate_quality_signals,
    read_hook_payload,
    log,
)


def handle(data):
    session_id = data.get("session_id")
    if not session_id:
        return

    tool_name = data.get("tool_name", "unknown")

    with open_db() as conn:
        ensure_session(conn, session_id)
        accumulate_quality_signals(conn, session_id, {
            "tool_failures": 1,
            "failures_by_tool": {tool_name: 1},
        })
        conn.commit()

    log(f"Tool failure | {tool_name}", session_id)


if __name__ == "__main__":
    data = read_hook_payload()
    handle(data)
