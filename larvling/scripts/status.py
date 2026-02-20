"""Larvling Status — quick overview of database state and plugin version.

Usage:
    python status.py
"""

import json
import os
import sys

from db import open_db, require_db, reconfigure_stdout


def main():
    reconfigure_stdout()
    require_db()

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    version = "unknown"
    plugin_json = os.path.join(plugin_root, ".claude-plugin", "plugin.json")
    if os.path.exists(plugin_json):
        with open(plugin_json, "r", encoding="utf-8") as f:
            version = json.load(f).get("version", version)

    with open_db() as conn:
        sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        loop_row = conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active "
            "FROM loops"
        ).fetchone()
        loops_total = loop_row["total"]
        loops_active = loop_row["active"] or 0

    print(f"Larvling v{version}")
    print(f"  Sessions:  {sessions}")
    print(f"  Messages:  {messages}")
    print(f"  Facts:     {facts}")
    print(f"  Loops:     {loops_total} ({loops_active} active)")


if __name__ == "__main__":
    main()
