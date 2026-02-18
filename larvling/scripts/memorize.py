"""
Larvling Memories - persistent facts and knowledge management.

Usage:
    python memorize.py --list                           # list active memories
    python memorize.py --list --all                     # include expired
    python memorize.py --add "claim" [options]          # add a memory
    python memorize.py --update M-NNN [field=value...]  # update a memory
    python memorize.py --delete M-NNN                   # delete a memory
    python memorize.py --search "query"                 # search memories
"""

import sys

from db import get_db, require_db, reconfigure_stdout, escape_like


def next_memory_id(conn):
    """Generate the next M-NNN id."""
    row = conn.execute(
        "SELECT id FROM memories WHERE id LIKE 'M-%' "
        "ORDER BY CAST(SUBSTR(id, 3) AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    if row:
        num = int(row[0][2:]) + 1
    else:
        num = 1
    return f"M-{num:03d}"


def add_memory(conn, claim, domain=None, tags=None, confidence="observed",
               source=None, notes=None):
    """Add a new memory. Returns the generated ID."""
    mid = next_memory_id(conn)
    conn.execute(
        "INSERT INTO memories (id, claim, domain, tags, confidence, source, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (mid, claim, domain, tags, confidence, source, notes),
    )
    conn.commit()
    return mid


def update_memory(conn, mid, **fields):
    """Update specified fields on a memory."""
    allowed = {
        "claim", "domain", "tags", "confidence", "source",
        "confirmed", "expires", "notes",
    }
    updates = []
    values = []
    for key, val in fields.items():
        if key in allowed:
            updates.append(f"{key} = ?")
            values.append(val)
    if not updates:
        return False
    values.append(mid)
    cursor = conn.execute(
        f"UPDATE memories SET {', '.join(updates)} WHERE id = ?",
        values,
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_memory(conn, mid):
    """Delete a memory by ID."""
    cursor = conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
    conn.commit()
    return cursor.rowcount > 0


def list_memories(conn, include_expired=False):
    """List memories. Returns list of Row objects."""
    if include_expired:
        return conn.execute(
            "SELECT * FROM memories ORDER BY established DESC"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM memories "
        "WHERE expires IS NULL OR expires > date('now') "
        "ORDER BY established DESC"
    ).fetchall()


def search_memories(conn, query):
    """Search memories by claim, notes, domain, and tags."""
    safe = escape_like(query)
    pattern = f"%{safe}%"
    return conn.execute(
        "SELECT * FROM memories "
        "WHERE (claim LIKE ? ESCAPE '\\' "
        "OR notes LIKE ? ESCAPE '\\' "
        "OR domain LIKE ? ESCAPE '\\' "
        "OR tags LIKE ? ESCAPE '\\') "
        "ORDER BY established DESC",
        (pattern, pattern, pattern, pattern),
    ).fetchall()


def format_memory(mem):
    """Format a single memory for display."""
    parts = [f"{mem['id']}  {mem['claim']}"]
    tags = []
    if mem["domain"]:
        tags.append(f"domain:{mem['domain']}")
    if mem["confidence"] and mem["confidence"] != "observed":
        tags.append(f"confidence:{mem['confidence']}")
    if mem["tags"]:
        tags.append(mem["tags"])
    if mem["expires"]:
        tags.append(f"expires:{mem['expires']}")
    if tags:
        parts.append(f"  [{', '.join(tags)}]")
    if mem["notes"]:
        parts.append(f"  Note: {mem['notes']}")
    return "".join(parts)


def main():
    reconfigure_stdout()

    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    require_db()
    conn = get_db()

    if sys.argv[1] == "--list":
        include_expired = "--all" in sys.argv
        memories = list_memories(conn, include_expired)
        if not memories:
            print("No memories found.")
        else:
            for mem in memories:
                print(format_memory(mem))
        conn.close()
        return

    if sys.argv[1] == "--add":
        if len(sys.argv) < 3:
            print(
                'Usage: --add "claim" [--domain D] [--tags T] '
                "[--confidence C] [--source S] [--notes N]",
                file=sys.stderr,
            )
            sys.exit(1)
        claim = sys.argv[2]
        kwargs = {}
        args = sys.argv[3:]
        for flag in ("--domain", "--tags", "--confidence", "--source", "--notes"):
            if flag in args:
                idx = args.index(flag)
                if idx + 1 < len(args):
                    kwargs[flag[2:]] = args[idx + 1]
        mid = add_memory(conn, claim, **kwargs)
        print(f"Memory {mid} added: {claim}")
        conn.close()
        return

    if sys.argv[1] == "--update":
        if len(sys.argv) < 4:
            print("Usage: --update M-NNN field=value [field=value...]", file=sys.stderr)
            sys.exit(1)
        mid = sys.argv[2]
        fields = {}
        for arg in sys.argv[3:]:
            if "=" in arg:
                key, val = arg.split("=", 1)
                fields[key] = val
        if update_memory(conn, mid, **fields):
            print(f"Memory {mid} updated")
        else:
            print(f"Memory {mid} not found or no valid fields", file=sys.stderr)
            sys.exit(1)
        conn.close()
        return

    if sys.argv[1] == "--delete":
        if len(sys.argv) < 3:
            print("Usage: --delete M-NNN", file=sys.stderr)
            sys.exit(1)
        mid = sys.argv[2]
        if delete_memory(conn, mid):
            print(f"Memory {mid} deleted")
        else:
            print(f"Memory {mid} not found", file=sys.stderr)
            sys.exit(1)
        conn.close()
        return

    if sys.argv[1] == "--search":
        if len(sys.argv) < 3:
            print('Usage: --search "query"', file=sys.stderr)
            sys.exit(1)
        results = search_memories(conn, sys.argv[2])
        if not results:
            print(f"No memories matching '{sys.argv[2]}'")
        else:
            for mem in results:
                print(format_memory(mem))
        conn.close()
        return

    print(__doc__.strip(), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
