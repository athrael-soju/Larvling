"""
Larvling Query - run arbitrary SQL against larvling.db.

Usage:
    python query.py "SQL"          # run SQL, table output
    python query.py "SQL" --json   # run SQL, JSON output
"""

import json
import os
import sys

from db import open_db, require_db, reconfigure_stdout


def format_table(rows):
    """Format rows as an aligned text table."""
    if not rows:
        return "No rows returned."

    keys = rows[0].keys()
    # Compute column widths
    widths = {k: len(k) for k in keys}
    str_rows = []
    for row in rows:
        str_row = {}
        for k in keys:
            val = row[k]
            s = "" if val is None else str(val)
            str_row[k] = s
            widths[k] = max(widths[k], len(s))
        str_rows.append(str_row)

    # Header
    header = "  ".join(k.ljust(widths[k]) for k in keys)
    sep = "  ".join("-" * widths[k] for k in keys)
    lines = [header, sep]

    for sr in str_rows:
        lines.append("  ".join(sr[k].ljust(widths[k]) for k in keys))

    lines.append(f"\n({len(str_rows)} rows)")
    return "\n".join(lines)


def main():
    reconfigure_stdout()

    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    sql = sys.argv[1]
    as_json = "--json" in sys.argv

    require_db()

    with open_db() as conn:
        try:
            cursor = conn.execute(sql)
        except Exception as e:
            print(f"SQL error: {e}", file=sys.stderr)
            sys.exit(1)

        # Detect if this is a SELECT (has results) or a write statement
        if cursor.description:
            rows = cursor.fetchall()
            if as_json:
                print(json.dumps([dict(r) for r in rows], indent=2, default=str))
            else:
                print(format_table(rows))
        else:
            conn.commit()
            print(f"{cursor.rowcount} row(s) affected.")


if __name__ == "__main__":
    main()
