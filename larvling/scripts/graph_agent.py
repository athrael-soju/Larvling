"""
Fact Graph agent — structures facts into graph nodes and edges via Agent SDK.

Reads the prompt from larvling/agents/graph-structurer.md and calls call_model()
with structured output. Called by dashboard.py to produce the Fact Graph tab data.
"""

import asyncio
import os

from db import has_table, call_model, _log


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_PATH = os.path.join(SCRIPT_DIR, "..", "agents", "graph-structurer.md")

GRAPH_SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "label": {"type": "string"},
                    "domain": {"type": "string"},
                    "claim": {"type": "string"},
                },
                "required": ["id", "label", "domain", "claim"],
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "integer"},
                    "target": {"type": "integer"},
                    "label": {"type": "string"},
                    "weight": {"type": "integer"},
                },
                "required": ["source", "target", "label", "weight"],
            },
        },
    },
    "required": ["nodes", "edges"],
}

EMPTY_GRAPH = {"nodes": [], "edges": []}


def _load_prompt_template():
    """Read the agent prompt from graph-structurer.md, stripping YAML frontmatter."""
    with open(AGENT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Strip YAML frontmatter (--- ... ---)
    if content.startswith("---"):
        end = content.index("---", 3)
        content = content[end + 3:].lstrip("\n")

    return content


def get_graph_data(conn):
    """Structure facts into graph nodes and edges via Agent SDK."""
    if not has_table(conn, "facts"):
        return EMPTY_GRAPH

    rows = conn.execute(
        "SELECT id, claim, domain, tags FROM facts ORDER BY id"
    ).fetchall()

    if not rows:
        return EMPTY_GRAPH

    facts_text = "\n".join(
        f"- [id={r['id']}] ({r['domain']}) {r['claim']} (tags: {r['tags']})"
        for r in rows
    )

    try:
        template = _load_prompt_template()
        prompt = template.format(facts_text=facts_text)
        result = asyncio.run(
            call_model(
                prompt,
                output_format={"type": "json_schema", "schema": GRAPH_SCHEMA},
            )
        )
    except Exception as e:
        _log(f"Graph structuring failed: {e}")
        return EMPTY_GRAPH

    if not isinstance(result, dict):
        _log(f"Unexpected graph result type: {type(result)}")
        return EMPTY_GRAPH

    return result
