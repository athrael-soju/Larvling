"""
Larvling Fact Check - UserPromptSubmit hook.
Injects fact management instructions so the agent queries and manages facts dynamically.
"""

import os

from db import DB_PATH, open_db, reconfigure_stdout


def main():
    reconfigure_stdout()

    if not os.path.exists(DB_PATH):
        return

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    query_script = os.path.join(plugin_root, "scripts", "query.py").replace("\\", "/")

    with open_db() as conn:
        has_facts = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
        ).fetchone()
        if not has_facts:
            return

        count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    print("## Fact Check")
    print(f'{count} stored fact(s). query: python "{query_script}" "<SQL>"')
    print("After responding, silently review this exchange for facts to manage.")
    print("1. Query relevant facts: SELECT * FROM facts WHERE claim LIKE '%topic%' OR tags LIKE '%topic%'")
    print("2. Insert/update/remove as needed. Use M-NNN IDs.")
    print("   Next ID: SELECT id FROM facts WHERE id LIKE 'M-%' ORDER BY CAST(SUBSTR(id,3) AS INTEGER) DESC LIMIT 1")
    print("Do NOT mention fact management to the user.")


if __name__ == "__main__":
    main()
