"""
Larvling Preflight — schema bootstrap.
Ensures the database and schema exist before any other hooks run.
"""

import os
import shutil

from db import (
    DB_PATH,
    SCHEMA_VERSION,
    open_db,
    reconfigure_stdout,
    create_schema,
    get_schema_version,
    set_schema_version,
    get_current_schema,
    get_desired_schema,
)


def ensure_schema():
    """Ensure current schema exists.

    Returns:
        'fresh'    - first install, schema created
        'current'  - schema up to date
        'migrate'  - version mismatch, migration context printed for Claude
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with open_db() as conn:
        has_tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()

        if not has_tables:
            create_schema(conn)
            set_schema_version(conn)
            return "fresh"

        db_version = get_schema_version(conn)
        if db_version == SCHEMA_VERSION:
            return "current"

        # Version mismatch - backup DB, then dump both schemas for Claude to handle
        old_schema = get_current_schema(conn)
        new_schema = get_desired_schema()

    backup_path = DB_PATH + f".v{db_version}.bak"
    shutil.copy2(DB_PATH, backup_path)

    print("# Larvling - Schema Migration Required\n")
    print(
        f"Database schema is version **{db_version}**, expected **{SCHEMA_VERSION}**."
    )
    print(f"A backup has been saved to `{backup_path}`.\n")
    print("## Current Schema (in database)")
    print(f"```sql\n{old_schema}\n```\n")
    print("## Desired Schema")
    print(f"```sql\n{new_schema}\n```\n")
    safe_path = DB_PATH.replace("\\", "/")
    print(
        "Please migrate the database at `"
        + safe_path
        + "` from the current schema to the desired schema."
    )
    print("Preserve all existing data. After migrating, run:")
    print(
        f"```python\npython -c \"import sqlite3; c=sqlite3.connect('{safe_path}'); c.execute('PRAGMA user_version={SCHEMA_VERSION}'); c.close()\"\n```"
    )

    return "migrate"


def main():
    if os.environ.get("LARVLING_INTERNAL"):
        return
    reconfigure_stdout()

    result = ensure_schema()

    if result == "fresh":
        print("# Larvling - First Run\n")
        print("Database created at `.claude/larvling.db`.")


if __name__ == "__main__":
    main()
