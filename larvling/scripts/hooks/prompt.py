"""UserPromptSubmit hook — logs the user's prompt and injects context hints."""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import (
    open_db,
    has_table,
    reconfigure_stdout,
    ensure_session,
    record_message,
    record_summary,
    log,
)


def strip_ide_tags(text):
    """Remove leading IDE context tags (opened files, selections) prepended by VSCode."""
    return re.sub(
        r"^(?:<ide_(?:opened_file|selection)>.*?</ide_(?:opened_file|selection)>\s*)+",
        "",
        text,
        flags=re.DOTALL,
    ).strip()


def inject_context(conn, session_id):
    """Print context hints (fact lookup, summary staleness) for the agent."""
    if has_table(conn, "facts"):
        fact_count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        query_script = os.path.join(
            scripts_dir, "query.py"
        ).replace("\\", "/")
        print(f'\n## Fact Context\n{fact_count} stored fact(s). '
              f'query: python "{query_script}" "<SQL>"\n'
              f'Search for facts relevant to this prompt '
              f'(e.g. WHERE claim LIKE \'%topic%\') and weave '
              f'them into your response naturally.')

    session = conn.execute(
        "SELECT summary_msg_count, agent_summary FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session:
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? "
            "AND role IN ('user', 'assistant')",
            (session_id,),
        ).fetchone()[0]
        summarized = session["summary_msg_count"] or 0

        if not session["agent_summary"] and msg_count >= 10:
            print(f'\n## Summary\nNo summary yet ({msg_count} messages). '
                  f'Offer /summarize via AskUserQuestion.')
        elif session["agent_summary"] and msg_count > summarized + 4:
            print(f'\n## Summary\nStale summary '
                  f'(covers {summarized}/{msg_count} messages). '
                  f'Offer /summarize via AskUserQuestion.')


def handle(data):
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

        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()[0]
        if count == 1:
            record_summary(conn, session_id, title=prompt)

        conn.commit()

        log(f"UserPromptSubmit: session={session_id[:8]}, exchange={count}")

        try:
            inject_context(conn, session_id)
        except Exception:
            pass  # Context injection is non-critical


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
