"""
Larvling Dashboard — generates a static HTML dashboard from all tables in larvling.db.
Zero dependencies: just sqlite3 + Python string templating.
"""

import sqlite3
import os
import sys
from html import escape

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "larvling.db")
HTML_PATH = os.path.join(PROJECT_ROOT, ".claude", "dashboard.html")


def get_tables(conn):
    """Discover all user tables in the database."""
    cur = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)
    return [r[0] for r in cur.fetchall()]


def get_columns(conn, table):
    """Get column names for a table."""
    cur = conn.execute(f"PRAGMA table_info([{table}])")
    return [row[1] for row in cur.fetchall()]


def get_rows(conn, table, columns, limit=100):
    """Fetch recent rows from a table, ordered by best available column."""
    order_col = "id"
    for candidate in ["timestamp", "created_at", "updated_at", "start_time"]:
        if candidate in columns:
            order_col = candidate
            break
    cur = conn.execute(f"SELECT * FROM [{table}] ORDER BY [{order_col}] DESC LIMIT ?", (limit,))
    return cur.fetchall()


def get_count(conn, table):
    """Get total row count for a table."""
    cur = conn.execute(f"SELECT COUNT(*) FROM [{table}]")
    return cur.fetchone()[0]


def render_table_html(table_name, columns, rows, count):
    """Render a single table as HTML."""
    header_cells = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body_rows = []
    for row in rows:
        cells = "".join(
            f"<td>{escape(str(v)) if v is not None else '<span class=\"null\">NULL</span>'}</td>"
            for v in row
        )
        body_rows.append(f"<tr>{cells}</tr>")

    showing = len(rows)
    subtitle = f"{count} row{'s' if count != 1 else ''}" + (f" (showing latest {showing})" if showing < count else "")

    return f"""
    <div class="table-section">
        <h2>{escape(table_name)} <span class="count">{subtitle}</span></h2>
        <div class="table-wrap">
            <table>
                <thead><tr>{header_cells}</tr></thead>
                <tbody>{"".join(body_rows) if body_rows else "<tr><td colspan='" + str(len(columns)) + "' class='empty'>No rows</td></tr>"}</tbody>
            </table>
        </div>
    </div>"""


def render_dashboard(tables_html, table_names):
    """Render the full dashboard page."""
    nav_links = " ".join(
        f'<a href="#{escape(t)}">{escape(t)}</a>' for t in table_names
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Larvling Dashboard</title>
<style>
    :root {{ --bg: #0d1117; --surface: #161b22; --border: #30363d; --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff; }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; background: var(--bg); color: var(--text); padding: 2rem; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; }}
    .meta {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 1.5rem; }}
    nav {{ margin-bottom: 2rem; display: flex; gap: 0.5rem; flex-wrap: wrap; }}
    nav a {{ color: var(--accent); text-decoration: none; padding: 0.25rem 0.75rem; border: 1px solid var(--border); border-radius: 4px; font-size: 0.85rem; }}
    nav a:hover {{ background: var(--surface); }}
    .table-section {{ margin-bottom: 2.5rem; }}
    .table-section h2 {{ font-size: 1.1rem; margin-bottom: 0.5rem; }}
    .count {{ color: var(--muted); font-weight: normal; font-size: 0.85rem; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
    th, td {{ text-align: left; padding: 0.5rem 0.75rem; border: 1px solid var(--border); max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    th {{ background: var(--surface); position: sticky; top: 0; }}
    tr:hover td {{ background: var(--surface); }}
    .null {{ color: var(--muted); font-style: italic; }}
    .empty {{ color: var(--muted); text-align: center; font-style: italic; }}
</style>
</head>
<body>
<h1>Larvling Dashboard</h1>
<p class="meta">Auto-generated from larvling.db</p>
<nav>{nav_links}</nav>
{tables_html}
</body>
</html>"""


def main():
    if not os.path.exists(DB_PATH):
        print("No database found at", DB_PATH, file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    tables = get_tables(conn)

    sections = []
    for table in tables:
        columns = get_columns(conn, table)
        count = get_count(conn, table)
        rows = get_rows(conn, table, columns)
        sections.append(render_table_html(table, columns, rows, count))

    conn.close()

    html = render_dashboard("\n".join(sections), tables)
    os.makedirs(os.path.dirname(HTML_PATH), exist_ok=True)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard generated: {HTML_PATH}")


if __name__ == "__main__":
    main()
