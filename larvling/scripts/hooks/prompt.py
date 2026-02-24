"""UserPromptSubmit hook — logs the user's prompt and injects context hints."""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import (
    open_db,
    has_table,
    ensure_session,
    record_message,
    record_summary,
    read_hook_payload,
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
    injected = []
    total_chars = 0

    if has_table(conn, "facts"):
        fact_count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        query_script = os.path.normpath(os.path.join(
            scripts_dir, "query.py"
        )).replace("\\", "/")
        text = (f'\n## Fact Context\n{fact_count} stored fact(s). '
                f'query: python "{query_script}" "<SQL>"\n'
                f'Search for facts relevant to this prompt '
                f'(e.g. WHERE claim LIKE \'%topic%\') and weave '
                f'them into your response naturally.')
        print(text)
        total_chars += len(text)
        injected.append(f"{fact_count} facts")

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
            text = (f'\n## Summary\nNo summary yet ({msg_count} messages). '
                    f'Offer /summarize via AskUserQuestion.')
            print(text)
            total_chars += len(text)
            injected.append("summary hint")
        elif session["agent_summary"] and msg_count > summarized + 4:
            text = (f'\n## Summary\nStale summary '
                    f'(covers {summarized}/{msg_count} messages). '
                    f'Offer /summarize via AskUserQuestion.')
            print(text)
            total_chars += len(text)
            injected.append("stale summary hint")

    if injected:
        tokens = max(1, total_chars // 4)
        log(f"Context | {' | '.join(injected)} | ~{tokens:,} tokens", session_id)


def handle(data):
    session_id = data.get("session_id")
    if not session_id:
        return

    prompt = strip_ide_tags(data.get("prompt", ""))
    if not prompt:
        return

    user_tokens = max(1, len(prompt) // 4)
    meta = {
        "cwd": data.get("cwd"),
        "permission_mode": data.get("permission_mode"),
        "usage": {"input_tokens_estimate": user_tokens},
    }

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

        # Detect skill/command invocations:
        # - Raw slash command: "/generate-dashboard", "/status"
        # - XML tags: <command-message>plugin:skill</command-message>
        cmd_match = re.search(
            r"<command-(?:message|name)>\s*/?(.+?)\s*</command-(?:message|name)>", prompt
        )
        if not cmd_match and re.fullmatch(r"/[\w:/-]+", prompt.strip()):
            cmd_match = re.fullmatch(r"/([\w:/-]+)", prompt.strip())
        if cmd_match:
            log(f"Skill | /{cmd_match.group(1)} | ~{user_tokens:,} tokens", session_id)
        else:
            log(f"Prompt #{count} | ~{user_tokens:,} tokens", session_id)

        try:
            inject_context(conn, session_id)
        except Exception:
            pass  # Context injection is non-critical


if __name__ == "__main__":
    data = read_hook_payload()
    handle(data)
