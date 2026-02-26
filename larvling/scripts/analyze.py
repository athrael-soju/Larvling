"""
Unified exchange analysis — Stop command hook.

Reads the transcript, parses the last exchange, calls Sonnet (via sdk.py)
to identify knowledge, sentiment, session tags, and tasks in a single
SDK call, then writes results to SQLite.
"""

import asyncio
import json
import os
import sys

from db import (
    open_db,
    has_table,
    ensure_session,
    record_message,
    store_message_metadata,
    fetch_session_tags,
    run_detached_or_inline,
    log,
)
from sdk import call_model
from transcript import parse_last_user_text, parse_last_turn, wait_for_transcript_stable


# ---------------------------------------------------------------------------
# Analysis prompt and schema
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """\
Analyze this conversation exchange and extract structured data.

USER said: {user_text}

AGENT responded: {agent_text}

## Knowledge-awareness

You can query the knowledge database to check for duplicates or related topics:

python "{query_script}" "<SQL>"

Two tables store knowledge:
- `topics` (id INTEGER PK, title, domain, tags, created, updated)
- `statements` (id INTEGER PK, topic_id INTEGER FK→topics(id), claim, created, updated)

Example queries:
- `SELECT t.id, t.title, s.id as sid, s.claim FROM topics t JOIN statements s ON s.topic_id = t.id WHERE s.claim LIKE '%keyword%'`
- `SELECT id, title, domain FROM topics WHERE title LIKE '%keyword%'`

Use this to avoid duplicates and consolidate related knowledge. \
For each knowledge item, set action to:
- **add_topic**: create a new topic with its first statement (no existing overlap)
- **add_statement**: add a new statement to an existing topic (include "topic_id")
- **update_statement**: refine an existing statement (include "statement_id")
- **update_topic**: update title/domain/tags of an existing topic (include "topic_id")
- **skip**: knowledge already exists unchanged — do NOT include it
Never delete data. To retire knowledge, update the statement or topic instead.

## Extraction

1. **knowledge** - Durable knowledge worth remembering across sessions:
   - From USER: personal info, professional info, preferences, interests \
(asking about ANY topic = an interest), decisions, opinions, workflow habits
   - From AGENT: key domain knowledge shared with the user (science, history, \
concepts) — NOT code-level implementation details
   - Each item: {{"topic_title": "...", "claim": "...", "domain": "...", "tags": "...", "action": "add_topic|add_statement|update_statement|...", "topic_id": N, "statement_id": N}}
   - Domains: personal, professional, preferences, interests, knowledge, technical, workflow
   - Tags: short topic label (e.g. "octopuses", "physics", "python")
   - **SKIP** (do NOT extract): bug reports, code fixes, line numbers, function \
signatures, file paths, refactoring notes, schema changes, documentation edits, \
changelog entries, or anything that will go stale when the code changes.
   - When in doubt, ask: "Would this still be useful in 30 days?" If not, skip it.
   - Prefer fewer, higher-quality items over many low-value ones.

2. **sentiment** - Single word for the user's mood in this exchange:
   - One of: focused, curious, frustrated, satisfied, neutral

3. **session_tags** - Updated session tag list (1-4 words each, max ~8 tags).
   Current session tags: {existing_tags}
   Return the FULL updated list — merge similar tags, drop tags no longer
   relevant, and add new tags from this exchange.
   If current tags is empty, just return new tags from this exchange.

4. **tasks** - Commitments or TODOs mentioned by either party:
   - Each task: {{"title": "...", "domain": "...", "priority": "low|medium|high", "horizon": "now|soon|later"}}
   - domain: same as knowledge domains
   - priority: how important (low/medium/high)
   - horizon: when to act (now/soon/later)

Return JSON:
{{
  "knowledge": [{{"topic_title": "...", "claim": "...", "domain": "...", "tags": "...", "action": "add_topic"}}],
  "sentiment": "focused",
  "session_tags": ["python", "deployment"],
  "tasks": [{{"title": "refactor auth module", "domain": "technical", "priority": "medium", "horizon": "soon"}}]
}}

If nothing to extract for a section, use empty list/string."""


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "knowledge": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic_title": {"type": "string"},
                    "claim": {"type": "string"},
                    "domain": {"type": "string"},
                    "tags": {"type": "string"},
                    "action": {"type": "string"},
                    "topic_id": {"type": "integer"},
                    "statement_id": {"type": "integer"},
                },
                "required": ["claim", "domain", "tags", "action"],
            },
        },
        "sentiment": {"type": "string"},
        "session_tags": {"type": "array", "items": {"type": "string"}},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "domain": {"type": "string"},
                    "priority": {"type": "string"},
                    "horizon": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
    "required": ["knowledge", "sentiment", "session_tags", "tasks"],
}


def build_extraction_prompt(user_text, agent_text, existing_tags=""):
    """Format the extraction prompt with the exchange text."""
    query_script = os.path.join(os.path.dirname(__file__), "query.py")
    return EXTRACTION_PROMPT.format(
        user_text=user_text or "(no user text)",
        agent_text=agent_text or "(no agent text)",
        existing_tags=existing_tags or "(none)",
        query_script=query_script.replace("\\", "/"),
    )


# ---------------------------------------------------------------------------
# Storage functions
# ---------------------------------------------------------------------------


def process_knowledge(conn, knowledge_list):
    """Process extracted knowledge into topics+statements tables.

    Handles 4 actions: add_topic, add_statement, update_statement, update_topic.
    Never deletes data — retirement is done via updates, not removal.
    Returns (topics_inserted, stmts_inserted, stmts_updated, topics_updated).
    """
    if not knowledge_list or not has_table(conn, "topics"):
        return 0, 0, 0, 0

    topics_inserted = 0
    stmts_inserted = 0
    stmts_updated = 0
    topics_updated = 0

    for item in knowledge_list:
        action = item.get("action", "").strip().lower()
        if action not in ("add_topic", "add_statement", "update_statement", "update_topic"):
            continue

        if action == "update_topic":
            topic_id = item.get("topic_id")
            if topic_id is None:
                continue
            try:
                topic_id = int(topic_id)
            except (ValueError, TypeError):
                continue
            if not conn.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,)).fetchone():
                continue
            title = item.get("topic_title", "").strip()
            domain = item.get("domain", "").strip()
            tags = item.get("tags", "").strip()
            if title:
                conn.execute(
                    "UPDATE topics SET title = ?, domain = COALESCE(?, domain), "
                    "tags = COALESCE(?, tags), updated = datetime('now') WHERE id = ?",
                    (title, domain or None, tags or None, topic_id),
                )
                topics_updated += 1
            continue

        if action == "update_statement":
            stmt_id = item.get("statement_id")
            if stmt_id is None:
                continue
            try:
                stmt_id = int(stmt_id)
            except (ValueError, TypeError):
                continue
            claim = item.get("claim", "").strip()
            if not claim:
                continue
            if not conn.execute("SELECT 1 FROM statements WHERE id = ?", (stmt_id,)).fetchone():
                continue
            conn.execute(
                "UPDATE statements SET claim = ?, updated = datetime('now') WHERE id = ?",
                (claim, stmt_id),
            )
            stmts_updated += 1
            continue

        if action == "add_statement":
            topic_id = item.get("topic_id")
            if topic_id is None:
                continue
            try:
                topic_id = int(topic_id)
            except (ValueError, TypeError):
                continue
            claim = item.get("claim", "").strip()
            if not claim:
                continue
            if not conn.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,)).fetchone():
                continue
            # Exact-match dedup safety net
            if conn.execute(
                "SELECT 1 FROM statements WHERE topic_id = ? AND claim = ?",
                (topic_id, claim),
            ).fetchone():
                continue
            conn.execute(
                "INSERT INTO statements (topic_id, claim) VALUES (?, ?)",
                (topic_id, claim),
            )
            stmts_inserted += 1
            continue

        # add_topic: new topic + first statement
        claim = item.get("claim", "").strip()
        if not claim:
            continue
        topic_title = item.get("topic_title", "").strip() or claim[:80]
        domain = item.get("domain", "knowledge").strip()
        tags = item.get("tags", "").strip()
        if not domain or not tags:
            continue

        # Exact-match dedup on claim
        if conn.execute(
            "SELECT 1 FROM statements WHERE claim = ?", (claim,)
        ).fetchone():
            continue

        conn.execute(
            "INSERT INTO topics (title, domain, tags) VALUES (?, ?, ?)",
            (topic_title, domain, tags),
        )
        topic_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO statements (topic_id, claim) VALUES (?, ?)",
            (topic_id, claim),
        )
        topics_inserted += 1
        stmts_inserted += 1

    return topics_inserted, stmts_inserted, stmts_updated, topics_updated


VALID_STATUS = {"open", "done", "dropped"}
VALID_PRIORITY = {"low", "medium", "high"}
VALID_HORIZON = {"now", "soon", "later"}


def process_tasks(conn, tasks_list):
    """Insert extracted tasks. Returns count inserted."""
    if not tasks_list or not has_table(conn, "tasks"):
        return 0

    inserted = 0
    for task in tasks_list:
        title = task.get("title", "").strip()
        if not title:
            continue
        domain = task.get("domain", "technical").strip()
        priority = task.get("priority", "medium").strip().lower()
        horizon = task.get("horizon", "later").strip().lower()

        # Validate enums, fallback to defaults
        if priority not in VALID_PRIORITY:
            priority = "medium"
        if horizon not in VALID_HORIZON:
            horizon = "later"

        # Dedup: skip if open task with same title exists
        if conn.execute(
            "SELECT 1 FROM tasks WHERE title = ? AND status = 'open'",
            (title,),
        ).fetchone():
            continue

        conn.execute(
            "INSERT INTO tasks (title, domain, priority, horizon) VALUES (?, ?, ?, ?)",
            (title, domain, priority, horizon),
        )
        inserted += 1

    return inserted



def store_tags(conn, session_id, tags):
    """Replace session tags with the model's consolidated list (deduped)."""
    if not tags:
        return  # Empty model response -> keep existing tags

    # Case-insensitive dedup, preserving model's ordering (most relevant first)
    seen = set()
    deduped = []
    for t in tags:
        t_clean = str(t).strip()
        if t_clean and t_clean.lower() not in seen:
            deduped.append(t_clean)
            seen.add(t_clean.lower())

    if not deduped:
        return

    conn.execute(
        "UPDATE sessions SET tags = ? WHERE id = ?",
        (", ".join(deduped), session_id),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _run(data):
    """Detached worker — called by run_detached_or_inline after payload parsing."""
    session_id = data.get("session_id")
    transcript_path = data.get("transcript_path")

    # Wait for transcript to finish writing before parsing
    wait_for_transcript_stable(transcript_path)

    # Get user text and agent text
    user_text = parse_last_user_text(transcript_path)
    agent_text, _, _ = parse_last_turn(transcript_path)

    if not user_text and not agent_text:
        log("extraction_skipped", session_id, reason="no text found")
        return

    # Read existing tags before the SDK call (brief read-only access)
    existing_tags = ""
    if session_id:
        try:
            with open_db() as conn:
                existing_tags = fetch_session_tags(conn, session_id)
        except Exception as e:
            log("extraction_error", session_id, context="tag fetch", error=str(e))

    try:
        prompt = build_extraction_prompt(user_text, agent_text, existing_tags)
        result, usage_info = asyncio.run(
            call_model(
                prompt,
                allowed_tools=["Bash"],
                output_format={"type": "json_schema", "schema": EXTRACTION_SCHEMA},
            )
        )
    except Exception as e:
        log("extraction_error", session_id, context="SDK call", error=str(e))
        return

    if not isinstance(result, dict):
        log("extraction_error", session_id, context="unexpected type", error=str(type(result)))
        return

    with open_db() as conn:
        # Ensure session row exists before writing session-scoped data
        if session_id:
            ensure_session(conn, session_id)

        # Knowledge (topics + statements)
        knowledge = result.get("knowledge", [])
        topics_ins, stmts_ins, stmts_upd, topics_upd = process_knowledge(conn, knowledge)

        # Tasks
        tasks_list = result.get("tasks", [])
        tasks_ins = process_tasks(conn, tasks_list)

        # Sentiment
        sentiment = result.get("sentiment")
        if session_id and isinstance(sentiment, str):
            store_message_metadata(conn, session_id, "assistant", "sentiment", sentiment, expected_content=agent_text)

        # Session tags
        session_tags = result.get("session_tags", [])
        if session_id and isinstance(session_tags, list):
            store_tags(conn, session_id, session_tags)

        # Record extraction as a system message with usage metadata
        if session_id:
            k_parts = []
            if topics_ins:
                k_parts.append(f"{topics_ins} topics")
            if stmts_ins:
                k_parts.append(f"{stmts_ins} statements")
            if stmts_upd or topics_upd:
                k_parts.append(f"{stmts_upd + topics_upd} updated")
            k_summary = ", ".join(k_parts) if k_parts else "no changes"

            t_summary = f"{tasks_ins} tasks" if tasks_ins else "no tasks"

            sys_content = f"Extraction: knowledge={k_summary}, {t_summary}"
            sys_meta = {"usage": usage_info} if usage_info else None
            record_message(conn, session_id, "system", sys_content, sys_meta)

        conn.commit()

    if topics_ins or stmts_ins or stmts_upd or topics_upd:
        k_data = {}
        if topics_ins:
            k_data["topics_inserted"] = topics_ins
        if stmts_ins:
            k_data["stmts_inserted"] = stmts_ins
        if stmts_upd:
            k_data["stmts_updated"] = stmts_upd
        if topics_upd:
            k_data["topics_updated"] = topics_upd
        log("knowledge", session_id, **k_data)

    if tasks_ins:
        log("tasks", session_id, inserted=tasks_ins)

    analysis_data = {}
    if result.get("sentiment"):
        analysis_data["sentiment"] = result["sentiment"]
    if result.get("session_tags"):
        tags = result["session_tags"]
        analysis_data["session_tags"] = tags if isinstance(tags, list) else [tags]
    if result.get("tasks"):
        analysis_data["tasks"] = len(result["tasks"])
    if usage_info and isinstance(usage_info, dict):
        analysis_data["input_tokens"] = usage_info.get("input_tokens", 0)
        analysis_data["output_tokens"] = usage_info.get("output_tokens", 0)

    log("analysis", session_id, **analysis_data)



if __name__ == "__main__":
    run_detached_or_inline(__file__, _run)
