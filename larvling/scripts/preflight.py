"""
Larvling Preflight — schema bootstrap.
Ensures the database and schema exist before any other hooks run.
"""

import os
import shutil
import sys

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
    py = os.path.basename(sys.executable)
    print(
        "Please migrate the database at `"
        + safe_path
        + "` from the current schema to the desired schema."
    )
    print("Preserve all existing data. After migrating, run:")
    print(
        f"```bash\n{py} -c \"import sqlite3; c=sqlite3.connect('{safe_path}'); c.execute('PRAGMA user_version={SCHEMA_VERSION}'); c.close()\"\n```"
    )

    return "migrate"


def check_dependencies():
    """Check if required Python packages are installed.

    Auto-installs from requirements.txt if missing.
    Returns True if all dependencies are satisfied, False otherwise.
    """
    try:
        import claude_agent_sdk  # noqa: F401
        return True
    except ImportError:
        pass

    # Auto-install missing dependency
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    req_file = os.path.join(plugin_root, "requirements.txt") if plugin_root else ""

    if sys.version_info < (3, 10):
        print("# Larvling - Python Version Too Old\n")
        print(f"Running Python **{sys.version_info.major}.{sys.version_info.minor}**, but `claude-agent-sdk` requires **3.10+**.\n")
        print("Install Python 3.10+ and ensure it is on your PATH (e.g. `brew install python@3.11`).")
        print("Without it, knowledge extraction, session tags, and task tracking are disabled.")
        return False

    import subprocess
    try:
        cmd = [sys.executable, "-m", "pip", "install", "--quiet"]
        if req_file and os.path.isfile(req_file):
            cmd += ["-r", req_file]
        else:
            cmd += ["claude-agent-sdk"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    except subprocess.CalledProcessError as e:
        print("# Larvling - Missing Dependency\n")
        print("`claude-agent-sdk` could not be auto-installed. Install it manually:\n")
        print("```bash")
        print(f"{sys.executable} -m pip install claude-agent-sdk")
        print("```\n")
        if e.stderr:
            print(f"Error: {e.stderr.strip()}\n")
        print("Without it, knowledge extraction, session tags, and task tracking are disabled.")
        return False

    # Verify import after install
    try:
        import claude_agent_sdk  # noqa: F401
        return True
    except ImportError:
        print("# Larvling - Missing Dependency\n")
        print("`claude-agent-sdk` was installed but cannot be imported. Try manually:\n")
        print("```bash")
        print(f"{sys.executable} -m pip install claude-agent-sdk")
        print("```\n")
        return False


def main():
    if os.environ.get("LARVLING_INTERNAL"):
        return
    reconfigure_stdout()

    check_dependencies()

    result = ensure_schema()

    if result == "fresh":
        print("# Larvling - First Run\n")
        print("Database created at `.claude/larvling.db`.")


if __name__ == "__main__":
    main()
