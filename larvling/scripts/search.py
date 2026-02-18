"""
Larvling Search - search session content using LIKE queries.

Usage:
    python search.py "query"                    # search sessions
    python search.py "query" --limit 10         # limit results
    python search.py "query" --context 120      # context snippet size
    python search.py "query" --json             # JSON output
"""

import json
import sys

from db import get_db, get_reflection, require_db, reconfigure_stdout


def extract_snippet(content, query, context_chars=80):
    """Extract a context snippet around the first match position."""
    lower = content.lower()
    pos = lower.find(query.lower())
    if pos == -1:
        return None

    start = max(0, pos - context_chars // 2)
    end = min(len(content), pos + len(query) + context_chars // 2)

    snippet = content[start:end].replace("\n", " ")
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."

    return snippet


def search_sessions(conn, query, limit=20, context_chars=80):
    """Search imprint content for query. Returns grouped results by session."""
    safe_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    rows = conn.execute(
        "SELECT encounter_id, content, role, timestamp FROM imprints "
        "WHERE content LIKE ? ESCAPE '\\' "
        "AND role IN ('user', 'assistant') "
        "ORDER BY id DESC",
        (f"%{safe_query}%",),
    ).fetchall()

    sessions = {}
    for row in rows:
        eid = row["encounter_id"]
        if eid not in sessions:
            sessions[eid] = {
                "session_id": eid,
                "title": "",
                "match_count": 0,
                "snippets": [],
            }
        sessions[eid]["match_count"] += 1

        content = row["content"] or ""
        if len(sessions[eid]["snippets"]) < 3:
            snippet = extract_snippet(content, query, context_chars)
            if snippet:
                sessions[eid]["snippets"].append(
                    {
                        "role": row["role"],
                        "timestamp": row["timestamp"] or "",
                        "snippet": snippet,
                    }
                )

    # Fetch session titles from reflections
    for eid, data in sessions.items():
        ref = get_reflection(conn, eid)
        if ref:
            data["title"] = ref["title"] or ""

    return list(sessions.values())[:limit]


def format_results(results, query):
    """Format search results as human-readable text."""
    if not results:
        return f"No results found for '{query}'"

    total = sum(r["match_count"] for r in results)
    lines = [
        f"# Search: '{query}'",
        f"{total} matches across {len(results)} sessions",
        "",
    ]

    for r in results:
        title = (r["title"] or "(untitled)").split("\n")[0][:80]
        lines.append(f"## {r['session_id'][:8]} - {title} ({r['match_count']} matches)")
        for s in r["snippets"]:
            role_name = "You" if s["role"] == "user" else "Agent"
            lines.append(f"  [{role_name}] {s['snippet']}")
        lines.append("")

    return "\n".join(lines)


def main():
    reconfigure_stdout()

    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    query = sys.argv[1]
    if not query.strip():
        print("Search query cannot be empty", file=sys.stderr)
        sys.exit(1)

    require_db()

    limit = 20
    context_chars = 80

    args = sys.argv[2:]
    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            try:
                limit = int(args[idx + 1])
            except ValueError:
                print(f"Invalid --limit value: {args[idx + 1]}", file=sys.stderr)
                sys.exit(1)
    if "--context" in args:
        idx = args.index("--context")
        if idx + 1 < len(args):
            try:
                context_chars = int(args[idx + 1])
            except ValueError:
                print(f"Invalid --context value: {args[idx + 1]}", file=sys.stderr)
                sys.exit(1)

    conn = get_db()
    results = search_sessions(conn, query, limit, context_chars)
    conn.close()

    if "--json" in args:
        print(json.dumps(results, indent=2))
    else:
        print(format_results(results, query))


if __name__ == "__main__":
    main()
