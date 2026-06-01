"""
Larvling Query - run arbitrary SQL against larvling.db.

Usage:
    python query.py "SQL"               # table output (cells <=200 chars, total <=~16KB)
    python query.py "SQL" --json        # JSON output (full, uncapped)
    python query.py "SQL" --full        # table output, no cell or size cap
    python query.py "SQL" --read-only   # reject non-SELECT statements
"""

import json
import os
import sys

from db import open_db, require_db, reconfigure_stdout


MAX_CELL_CHARS = 200
MAX_TABLE_CHARS = 16000


def format_table(rows, max_cell=MAX_CELL_CHARS, max_chars=MAX_TABLE_CHARS):
    """Format rows as an aligned text table.

    Two independent caps keep output bounded so a careless query can't
    flood the caller:

    * ``max_cell`` — each value is collapsed to one line and truncated
      (with an ellipsis) so one oversized value can't pad every row out
      to its width.
    * ``max_chars`` — total table size; once exceeded, remaining rows are
      omitted with a footer telling the caller to narrow or use --full.

    Pass ``None`` for either to disable that cap.
    """
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
            # Collapse whitespace/newlines so multi-line values stay aligned.
            s = " ".join(s.split())
            if max_cell is not None and len(s) > max_cell:
                s = s[: max_cell - 1] + "…"
            str_row[k] = s
            widths[k] = max(widths[k], len(s))
        str_rows.append(str_row)

    # Header
    header = "  ".join(k.ljust(widths[k]) for k in keys)
    sep = "  ".join("-" * widths[k] for k in keys)
    lines = [header, sep]

    # Emit rows until the total-size budget is hit. Always show at least
    # one data row so a single very wide row still returns something.
    total = len(header) + len(sep) + 2
    shown = 0
    for sr in str_rows:
        line = "  ".join(sr[k].ljust(widths[k]) for k in keys)
        if max_chars is not None and shown >= 1 and total + len(line) + 1 > max_chars:
            break
        lines.append(line)
        total += len(line) + 1
        shown += 1

    if shown < len(str_rows):
        lines.append(
            f"\n… showing {shown} of {len(str_rows)} rows "
            f"({len(str_rows) - shown} omitted to stay under the output cap). "
            f"Narrow with LIMIT/WHERE, or pass --full."
        )
    else:
        lines.append(f"\n({len(str_rows)} rows)")
    return "\n".join(lines)


def main():
    reconfigure_stdout()

    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    sql = sys.argv[1]
    as_json = "--json" in sys.argv
    read_only = "--read-only" in sys.argv
    full = "--full" in sys.argv

    require_db()

    with open_db() as conn:
        if read_only:
            conn.execute("PRAGMA query_only = ON")
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
                print(format_table(
                    rows,
                    max_cell=None if full else MAX_CELL_CHARS,
                    max_chars=None if full else MAX_TABLE_CHARS,
                ))
        else:
            conn.commit()
            print(f"{cursor.rowcount} row(s) affected.")


if __name__ == "__main__":
    main()
