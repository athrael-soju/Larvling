"""Larvling Fact CLI — remember, recall, forget commands.

Usage:
    python facts.py remember <fact>   # store a fact
    python facts.py recall [search]   # list or search facts
    python facts.py forget <search>   # find matching facts for deletion
"""

import sys

from db import open_db, escape_like, reconfigure_stdout


def _next_fact_id(conn):
    """Get the next M-NNN fact ID."""
    row = conn.execute(
        "SELECT id FROM facts WHERE id LIKE 'M-%' "
        "ORDER BY CAST(SUBSTR(id, 3) AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    num = int(row["id"].split("-")[1]) + 1 if row else 1
    return f"M-{num:03d}"


def cli_remember(args):
    """Store a fact. Updates if a similar one exists, otherwise inserts."""
    with open_db() as conn:
        pattern = f"%{escape_like(args)}%"
        rows = conn.execute(
            "SELECT id, claim FROM facts WHERE claim LIKE ? ESCAPE '\\'",
            (pattern,),
        ).fetchall()

        # Exact match -> already stored
        for row in rows:
            if row["claim"].lower().strip() == args.lower().strip():
                print(f"Already stored: {row['id']} — {row['claim']}")
                return

        # Similar matches -> report for main agent to decide
        if rows:
            print("Similar facts found:")
            for row in rows:
                print(f"  {row['id']}: {row['claim']}")
            print(f"\nNew fact: {args}")
            print("Use /query to UPDATE an existing fact or INSERT a new one.")
            return

        # No match -> insert
        new_id = _next_fact_id(conn)
        conn.execute(
            "INSERT INTO facts (id, claim) VALUES (?, ?)",
            (new_id, args),
        )
        conn.commit()
        print(f"Stored: {new_id} — {args}")


def cli_recall(args):
    """Search or list facts."""
    with open_db() as conn:
        if not args.strip():
            rows = conn.execute(
                "SELECT id, claim, domain, tags, established FROM facts "
                "ORDER BY established DESC"
            ).fetchall()
        else:
            pattern = f"%{escape_like(args)}%"
            rows = conn.execute(
                "SELECT id, claim, domain, tags, established FROM facts "
                "WHERE claim LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' "
                "OR domain LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\'",
                (pattern, pattern, pattern, pattern),
            ).fetchall()

        if not rows:
            print("No matching facts found.")
            return

        for row in rows:
            line = f"{row['id']}: {row['claim']}"
            extras = []
            if row["domain"]:
                extras.append(f"domain={row['domain']}")
            if row["tags"]:
                extras.append(f"tags={row['tags']}")
            if extras:
                line += f"  ({', '.join(extras)})"
            print(line)
        print(f"\n({len(rows)} facts)")


def cli_forget(args):
    """Find matching facts for deletion (does NOT delete)."""
    with open_db() as conn:
        pattern = f"%{escape_like(args)}%"
        rows = conn.execute(
            "SELECT id, claim, domain, tags FROM facts "
            "WHERE id = ? OR claim LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\'",
            (args, pattern, pattern),
        ).fetchall()

        if not rows:
            print("No matching facts found.")
            return

        print("Matching facts:")
        for row in rows:
            line = f"  {row['id']}: {row['claim']}"
            extras = []
            if row["domain"]:
                extras.append(f"domain={row['domain']}")
            if row["tags"]:
                extras.append(f"tags={row['tags']}")
            if extras:
                line += f"  ({', '.join(extras)})"
            print(line)


def main():
    reconfigure_stdout()

    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    args = " ".join(sys.argv[2:])

    if command == "remember":
        cli_remember(args)
    elif command == "recall":
        cli_recall(args)
    elif command == "forget":
        cli_forget(args)
    else:
        print(f"Unknown fact command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
