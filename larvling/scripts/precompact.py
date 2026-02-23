"""
Larvling PreCompact hook.
Injects critical session context before compaction so it survives summarization.
"""

import os

from db import DB_PATH, open_db, reconfigure_stdout, has_table


def main():
    if os.environ.get("LARVLING_INTERNAL"):
        return
    reconfigure_stdout()

    if not os.path.exists(DB_PATH):
        return

    lines = []

    try:
        with open_db() as conn:
            # Current session topics
            session_id = os.environ.get("CLAUDE_SESSION_ID", "")
            if session_id:
                row = conn.execute(
                    "SELECT title, topics FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                if row:
                    if row["title"]:
                        lines.append(
                            f"Current session: {row['title']}"
                        )
                    if row["topics"]:
                        lines.append(f"Session topics: {row['topics']}")

            # Recent facts (most likely to be relevant)
            if has_table(conn, "facts"):
                fact_count = conn.execute(
                    "SELECT COUNT(*) FROM facts"
                ).fetchone()[0]
                if fact_count:
                    lines.append(f"Stored facts: {fact_count}")
                    recent = conn.execute(
                        "SELECT id, claim FROM facts "
                        "ORDER BY COALESCE(updated, created) DESC LIMIT 5"
                    ).fetchall()
                    for r in recent:
                        lines.append(f"- Fact {r['id']}: {r['claim']}")

            # Reminder about Larvling commands
            lines.append(
                "Larvling commands: /remember, /recall, /forget, "
                "/sessions, /summarize, /export, /status, /query, "
                "/generate-dashboard"
            )
    except Exception:
        return

    if lines:
        print("# Larvling Context (preserve across compaction)\n")
        print("\n".join(lines))


if __name__ == "__main__":
    main()
