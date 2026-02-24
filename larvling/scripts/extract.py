"""
Unified extraction via Claude Agent SDK.

Called as a Stop command hook. Reads the transcript, extracts the last
exchange, calls Sonnet to identify facts, sentiment, topics, and action
items in a single SDK call, then writes results to SQLite.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile

from db import (
    open_db,
    has_table,
    parse_meta,
    reconfigure_stdout,
    ensure_session,
    log,
)
from transcript import parse_last_user_text, parse_last_turn, wait_for_transcript_stable

# ---------------------------------------------------------------------------
# Agent SDK call
# ---------------------------------------------------------------------------


async def call_model(prompt, allowed_tools=None, max_turns=None, output_format=None):
    """Call the LLM via Agent SDK and return the response.

    Returns structured_output (dict) when output_format is set,
    otherwise returns response text (str).
    Sets LARVLING_INTERNAL to prevent sub-agent from triggering hooks.
    """
    from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
    from claude_agent_sdk._internal.message_parser import parse_message  # noqa: PLC2701
    from claude_agent_sdk._errors import MessageParseError  # noqa: PLC2701
    import claude_agent_sdk._internal.client as _sdk_client  # noqa: PLC2701

    # Patch parse_message to skip unknown message types instead of crashing.
    # The SDK (as of 0.1.39) doesn't handle rate_limit_event and other CLI
    # message types, which kills the async generator mid-stream and loses
    # all subsequent messages including the ResultMessage with structured_output.
    # Note: not concurrent-safe — callers use asyncio.run() (one loop at a time).
    def _tolerant_parse(data):
        try:
            return parse_message(data)
        except MessageParseError:
            return None

    opts = {"model": "claude-sonnet-4-6", "allowed_tools": allowed_tools or []}
    if max_turns is not None:
        opts["max_turns"] = max_turns
    if output_format:
        opts["output_format"] = output_format
    options = ClaudeAgentOptions(**opts)

    os.environ["LARVLING_INTERNAL"] = "1"
    # Remove CLAUDECODE to prevent "nested session" guard in the subprocess
    saved_claudecode = os.environ.pop("CLAUDECODE", None)
    setattr(_sdk_client, "parse_message", _tolerant_parse)

    response_text = ""
    structured = None
    result_subtype = None
    try:
        async for msg in query(prompt=prompt, options=options):
            if msg is None:
                continue
            if isinstance(msg, ResultMessage):
                result_subtype = getattr(msg, "subtype", None)
                if msg.structured_output:
                    structured = msg.structured_output
                continue
            content = getattr(msg, "content", None)
            if not content:
                continue
            for block in content:
                text = getattr(block, "text", None)
                if text:
                    response_text += text
    finally:
        os.environ.pop("LARVLING_INTERNAL", None)
        if saved_claudecode is not None:
            os.environ["CLAUDECODE"] = saved_claudecode
        setattr(_sdk_client, "parse_message", parse_message)

    if structured is not None:
        return structured

    if output_format:
        raise RuntimeError(
            f"Structured output not returned (subtype={result_subtype})"
        )

    return response_text.strip()


# ---------------------------------------------------------------------------
# Unified extraction via Agent SDK
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """\
Analyze this conversation exchange and extract structured data.

USER said: {user_text}

AGENT responded: {agent_text}

## Fact-awareness

You can query the facts database to check for duplicates or stale facts:

python "{query_script}" "<SQL>"

The `facts` table has columns: id (INTEGER PK), claim, domain, tags, created, updated.

Use this to avoid duplicates, consolidate related facts, and clean up stale \
or outdated entries. When a new fact overlaps with an existing one, **update** \
the existing row to be more comprehensive rather than inserting alongside it. \
For each fact, set action to:
- **insert**: genuinely new fact with no existing overlap
- **update**: existing fact should be consolidated or refined (include "id")
- **delete**: existing fact is stale, outdated, or duplicated (include "id")
- **skip**: fact already exists unchanged — do NOT include it

## Extraction

1. **facts** - Durable facts worth remembering across sessions:
   - From USER: personal info, professional info, preferences, interests \
(asking about ANY topic = an interest), decisions, opinions, workflow habits
   - From AGENT: key domain knowledge shared with the user (science, history, \
concepts) — NOT code-level implementation details
   - Each fact: {{"claim": "...", "domain": "...", "tags": "...", "action": "insert|update", "id": N (update only)}}
   - Domains: personal, professional, preferences, interests, knowledge, technical
   - Tags: short topic label (e.g. "octopuses", "physics", "python")
   - **SKIP** (do NOT extract): bug reports, code fixes, line numbers, function \
signatures, file paths, refactoring notes, schema changes, documentation edits, \
changelog entries, or anything that will go stale when the code changes.
   - When in doubt, ask: "Would this fact still be useful in 30 days?" If not, skip it.
   - Prefer fewer, higher-quality facts over many low-value ones.

2. **sentiment** - Single word for the user's mood in this exchange:
   - One of: focused, curious, frustrated, satisfied, neutral

3. **topics** - Updated session topic list (1-4 words each, max ~8 topics).
   Current session topics: {existing_topics}
   Return the FULL updated list — merge similar topics, drop topics no longer
   relevant, and add new topics from this exchange.
   If current topics is empty, just return new topics from this exchange.

4. **action_items** - Commitments or TODOs mentioned by either party

Return JSON:
{{
  "facts": [{{"claim": "...", "domain": "...", "tags": "...", "action": "insert"}}],
  "sentiment": "focused",
  "topics": ["python", "deployment"],
  "action_items": ["refactor auth module"]
}}

If nothing to extract for a section, use empty list/string."""


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "domain": {"type": "string"},
                    "tags": {"type": "string"},
                    "action": {"type": "string"},
                    "id": {"type": "integer"},
                },
                "required": ["claim", "domain", "tags", "action"],
            },
        },
        "sentiment": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
        "action_items": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["facts", "sentiment", "topics", "action_items"],
}


def build_extraction_prompt(user_text, agent_text, existing_topics=""):
    """Format the extraction prompt with the exchange text."""
    query_script = os.path.join(os.path.dirname(__file__), "query.py")
    return EXTRACTION_PROMPT.format(
        user_text=user_text or "(no user text)",
        agent_text=agent_text or "(no agent text)",
        existing_topics=existing_topics or "(none)",
        query_script=query_script.replace("\\", "/"),
    )


# ---------------------------------------------------------------------------
# Storage functions
# ---------------------------------------------------------------------------


def process_facts(conn, facts_list):
    """Insert or update extracted facts. Returns count stored/updated."""
    if not facts_list or not has_table(conn, "facts"):
        return 0, 0, 0

    inserted = 0
    updated = 0
    deleted = 0

    for fact in facts_list:
        action = fact.get("action", "insert").strip().lower()
        if action == "skip":
            continue

        if action == "delete":
            existing_id = fact.get("id")
            if existing_id is None:
                continue
            try:
                existing_id = int(existing_id)
            except (ValueError, TypeError):
                continue
            row = conn.execute(
                "SELECT 1 FROM facts WHERE id = ?", (existing_id,)
            ).fetchone()
            if not row:
                continue
            conn.execute("DELETE FROM facts WHERE id = ?", (existing_id,))
            deleted += 1
            continue

        claim = fact.get("claim", "").strip()
        if not claim:
            continue
        domain = fact.get("domain", "knowledge").strip()
        tags = fact.get("tags", "").strip()

        if not domain or not tags:
            continue

        if action == "update":
            existing_id = fact.get("id")
            if existing_id is None:
                continue
            try:
                existing_id = int(existing_id)
            except (ValueError, TypeError):
                continue
            row = conn.execute(
                "SELECT 1 FROM facts WHERE id = ?", (existing_id,)
            ).fetchone()
            if not row:
                continue
            conn.execute(
                "UPDATE facts SET claim = ?, domain = ?, tags = ?, "
                "updated = date('now') WHERE id = ?",
                (claim, domain, tags, existing_id),
            )
            updated += 1
        else:
            # Insert — keep exact-match dedup as safety net
            existing = conn.execute(
                "SELECT 1 FROM facts WHERE claim = ?", (claim,)
            ).fetchone()
            if existing:
                continue

            conn.execute(
                "INSERT INTO facts (claim, domain, tags) VALUES (?, ?, ?)",
                (claim, domain, tags),
            )
            inserted += 1

    return inserted, updated, deleted


def store_message_metadata(conn, session_id, field, value, expected_content=None):
    """Store a field in the metadata of the last assistant message."""
    if not value:
        return

    row = conn.execute(
        "SELECT id, content, metadata FROM messages "
        "WHERE session_id = ? AND role = 'assistant' "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row:
        return

    # Don't attach metadata to a message from a different turn
    if expected_content and row["content"] != expected_content:
        return

    meta = parse_meta(row["metadata"])
    meta[field] = value
    conn.execute(
        "UPDATE messages SET metadata = ? WHERE id = ?",
        (json.dumps(meta), row["id"]),
    )


def fetch_existing_topics(conn, session_id):
    """Read the current topics string for a session."""
    row = conn.execute(
        "SELECT topics FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row and row["topics"]:
        return row["topics"]
    return ""


def store_topics(conn, session_id, topics):
    """Replace session topics with the model's consolidated list (deduped)."""
    if not topics:
        return  # Empty model response -> keep existing topics

    # Case-insensitive dedup, preserving model's ordering (most relevant first)
    seen = set()
    deduped = []
    for t in topics:
        t_clean = str(t).strip()
        if t_clean and t_clean.lower() not in seen:
            deduped.append(t_clean)
            seen.add(t_clean.lower())

    if not deduped:
        return

    conn.execute(
        "UPDATE sessions SET topics = ? WHERE id = ?",
        (", ".join(deduped), session_id),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _spawn_detached(payload_path):
    """Spawn self as a detached process that outlives the parent."""
    creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [sys.executable, __file__, "--detached", payload_path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation,
        start_new_session=(os.name != "nt"),
    )


def main():
    if os.environ.get("LARVLING_INTERNAL"):
        return
    reconfigure_stdout()

    # --detached mode: read payload from temp file (spawned by parent)
    if "--detached" in sys.argv:
        payload_path = sys.argv[sys.argv.index("--detached") + 1]
        try:
            with open(payload_path, "r", encoding="utf-8") as f:
                raw = f.read()
        finally:
            try:
                os.unlink(payload_path)
            except OSError:
                pass
    else:
        # Normal mode: read stdin, spawn detached child, exit immediately
        try:
            raw = sys.stdin.buffer.read().decode("utf-8")
        except Exception as e:
            log(f"stdin read failed: {e}")
            return

        if not raw.strip():
            return

        # Write payload to temp file and spawn detached child
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        tmp.write(raw)
        tmp.close()
        _spawn_detached(tmp.name)
        return  # Parent exits immediately

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    session_id = data.get("session_id")
    transcript_path = data.get("transcript_path")

    # Wait for transcript to finish writing before parsing
    wait_for_transcript_stable(transcript_path)

    # Get user text and agent text
    user_text = parse_last_user_text(transcript_path)
    agent_text, _ = parse_last_turn(transcript_path)

    if not user_text and not agent_text:
        log(f"Extraction skipped: session={session_id[:8] if session_id else '?'}, no text found")
        return

    # Read existing topics before the SDK call (brief read-only access)
    existing_topics = ""
    if session_id:
        try:
            with open_db() as conn:
                existing_topics = fetch_existing_topics(conn, session_id)
        except Exception as e:
            log(f"Topic fetch failed: {e}")

    try:
        prompt = build_extraction_prompt(user_text, agent_text, existing_topics)
        result = asyncio.run(
            call_model(
                prompt,
                allowed_tools=["Bash"],
                output_format={"type": "json_schema", "schema": EXTRACTION_SCHEMA},
            )
        )
    except Exception as e:
        log(f"SDK call failed: {e}")
        return

    if not isinstance(result, dict):
        log(f"Unexpected result type: {type(result)}")
        return

    with open_db() as conn:
        # Ensure session row exists before writing session-scoped data
        if session_id:
            ensure_session(conn, session_id)

        # Facts
        facts = result.get("facts", [])
        inserted, updated, deleted = process_facts(conn, facts)

        # Sentiment
        sentiment = result.get("sentiment")
        if session_id and isinstance(sentiment, str):
            store_message_metadata(conn, session_id, "sentiment", sentiment, expected_content=agent_text)

        # Topics
        topics = result.get("topics", [])
        if session_id and isinstance(topics, list):
            store_topics(conn, session_id, topics)

        # Action items
        action_items = result.get("action_items", [])
        if session_id and isinstance(action_items, list) and action_items:
            store_message_metadata(conn, session_id, "action_items", action_items, expected_content=agent_text)

        conn.commit()

    if inserted or updated or deleted:
        parts = []
        if inserted:
            parts.append(f"inserted {inserted}")
        if updated:
            parts.append(f"updated {updated}")
        if deleted:
            parts.append(f"deleted {deleted}")
        log(f"Facts: {', '.join(parts)}")

    extras = []
    if result.get("sentiment"):
        extras.append(f"sentiment={result['sentiment']}")
    if result.get("topics"):
        extras.append(f"topics={result['topics']}")
    if result.get("action_items"):
        extras.append(f"actions={len(result['action_items'])}")
    if extras:
        log(f"Extraction: {', '.join(extras)}")



if __name__ == "__main__":
    main()
