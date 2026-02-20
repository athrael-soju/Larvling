"""Larvling UserPromptSubmit hook.

Logs the user's prompt, sets session title on first message,
and injects relevant facts from the knowledge base.
"""

import json
import os
import re
import sys

from db import (
    open_db,
    log_error,
    escape_like,
    ensure_session,
    record_message,
    record_summary,
    reconfigure_stdout,
)
from transcript import strip_ide_tags


def inject_relevant_facts(conn, prompt):
    """Query facts table for content relevant to the user's prompt."""
    words = list(dict.fromkeys(
        w for w in re.findall(r"[a-zA-Z_]{5,}", prompt)
    ))[:6]
    if not words:
        return

    clauses, params = [], []
    for w in words:
        safe = escape_like(w.lower())
        clauses.append(
            "(LOWER(claim) LIKE ? ESCAPE '\\' "
            "OR LOWER(domain) LIKE ? ESCAPE '\\' "
            "OR LOWER(tags) LIKE ? ESCAPE '\\')"
        )
        params.extend([f"%{safe}%"] * 3)

    facts = conn.execute(
        f"SELECT id, claim FROM facts WHERE {' OR '.join(clauses)} LIMIT 5",
        params,
    ).fetchall()

    if facts:
        print("\n## Relevant Facts")
        for f in facts:
            print(f"- [{f['id']}] {f['claim']}")
        print()


def handle_user_prompt(data):
    """Log the user's prompt from a UserPromptSubmit event."""
    if os.environ.get("LARVLING_AGENT"):
        return

    session_id = data.get("session_id")
    if not session_id:
        return

    prompt = strip_ide_tags(data.get("prompt", ""))
    if not prompt:
        return

    meta = {"cwd": data.get("cwd"), "permission_mode": data.get("permission_mode")}

    with open_db() as conn:
        ensure_session(conn, session_id)
        record_message(conn, session_id, "user", prompt, meta)

        # Set title on first user message
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()[0]
        if count == 1:
            record_summary(conn, session_id, title=prompt)

        conn.commit()

        # Inject relevant facts after commit (read-only from here)
        inject_relevant_facts(conn, prompt)


def main():
    reconfigure_stdout()
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception as e:
        log_error(f"hook_prompt stdin read failed: {e}")
        return

    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log_error(f"hook_prompt JSON parse failed ({len(raw)} bytes): {e}")
        return

    handle_user_prompt(data)


if __name__ == "__main__":
    main()
