"""
Unified extraction via Claude Agent SDK.

Called as a Stop command hook. Reads the transcript, extracts the last
exchange, calls Sonnet to identify facts, sentiment, topics, and action
items in a single SDK call, then writes results to SQLite.
"""

import asyncio
import json
import os
import re
import sys
import time

from db import open_db, has_table, parse_meta, reconfigure_stdout, ensure_session, _log

from hooks import parse_last_turn, wait_for_transcript_stable, _is_real_user_message

# ---------------------------------------------------------------------------
# Transcript parsing — extract user text from the last exchange
# ---------------------------------------------------------------------------


def parse_last_user_text(transcript_path):
    """Return the last real user message text from the transcript."""
    if not transcript_path or not os.path.exists(transcript_path):
        return None

    lines = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(raw)

    for i in range(len(lines) - 1, -1, -1):
        try:
            entry = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if _is_real_user_message(entry):
            msg = entry.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                    if not (isinstance(b, dict) and b.get("type") == "tool_result")
                ]
                return " ".join(p for p in parts if p).strip()

    return None


# ---------------------------------------------------------------------------
# Unified extraction via Agent SDK
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """\
Analyze this conversation exchange and extract structured data. Return ONLY valid JSON.

USER said: {user_text}

AGENT responded: {agent_text}

Extract ALL of the following:

1. **facts** - Storable facts about the user or key knowledge shared:
   - From USER: personal info, professional info, preferences, interests \
(asking about ANY topic = an interest), decisions, opinions
   - From AGENT: key knowledge facts shared with the user
   - Each fact: {{"claim": "...", "domain": "...", "tags": "..."}}
   - Domains: personal, professional, preferences, interests, knowledge, technical
   - Tags: short topic label (e.g. "octopuses", "physics", "python")

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
  "facts": [{{"claim": "...", "domain": "...", "tags": "..."}}],
  "sentiment": "focused",
  "topics": ["python", "deployment"],
  "action_items": ["refactor auth module"]
}}

If nothing to extract for a section, use empty list/string:
{{"facts": [], "sentiment": "neutral", "topics": [], "action_items": []}}
JSON only, no markdown fences."""


async def call_sdk(user_text, agent_text, existing_topics=""):
    """Call Sonnet via Agent SDK to extract facts, sentiment, topics, action items."""
    from claude_code_sdk import query, ClaudeCodeOptions

    prompt = EXTRACTION_PROMPT.format(
        user_text=user_text or "(no user text)",
        agent_text=agent_text or "(no agent text)",
        existing_topics=existing_topics or "(none)",
    )

    options = ClaudeCodeOptions(
        model="claude-sonnet-4-6",
        max_turns=1,
        allowed_tools=[],
    )

    # Prevent the sub-agent from triggering Larvling hooks
    os.environ["LARVLING_INTERNAL"] = "1"

    response_text = ""
    try:
        async for msg in query(prompt=prompt, options=options):
            content = getattr(msg, "content", None)
            if not content:
                continue

            for block in content:
                text = getattr(block, "text", None)
                if text:
                    response_text += text
    except Exception as e:
        if not response_text:
            raise e
    finally:
        os.environ.pop("LARVLING_INTERNAL", None)

    return response_text


# ---------------------------------------------------------------------------
# Storage functions
# ---------------------------------------------------------------------------


def get_next_fact_id(conn):
    """Get the next M-NNN id."""
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(id, 3) AS INTEGER)) FROM facts WHERE id LIKE 'M-%'"
    ).fetchone()
    if row and row[0] is not None:
        return row[0] + 1
    return 1


def store_facts(conn, facts_list):
    """Insert extracted facts into the DB. Returns count stored."""
    if not facts_list or not has_table(conn, "facts"):
        return 0

    next_id = get_next_fact_id(conn)
    count = 0

    for fact in facts_list:
        claim = fact.get("claim", "").strip()
        if not claim:
            continue
        domain = fact.get("domain", "knowledge").strip()
        tags = fact.get("tags", "").strip()

        fid = f"M-{next_id:03d}"
        next_id += 1

        existing = conn.execute(
            "SELECT 1 FROM facts WHERE claim = ?", (claim,)
        ).fetchone()
        if existing:
            continue

        conn.execute(
            "INSERT INTO facts (id, claim, domain, tags, confidence, "
            "source, established) VALUES (?, ?, ?, ?, 'observed', "
            "'conversation', date('now'))",
            (fid, claim, domain, tags or None),
        )
        count += 1

    return count


def store_sentiment(conn, session_id, sentiment, expected_content=None):
    """Store sentiment in the metadata of the last assistant message."""
    if not sentiment:
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
    meta["sentiment"] = sentiment
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


def store_action_items(conn, session_id, action_items, expected_content=None):
    """Store action items in the metadata of the last assistant message."""
    if not action_items:
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
    meta["action_items"] = action_items
    conn.execute(
        "UPDATE messages SET metadata = ? WHERE id = ?",
        (json.dumps(meta), row["id"]),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if os.environ.get("LARVLING_INTERNAL"):
        return
    reconfigure_stdout()

    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception as e:
        _log(f"stdin read failed: {e}")
        return

    if not raw.strip():
        return

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
        return

    # Read existing topics before the SDK call (brief read-only access)
    existing_topics = ""
    if session_id:
        try:
            with open_db() as conn:
                existing_topics = fetch_existing_topics(conn, session_id)
        except Exception:
            pass

    try:
        response = asyncio.run(call_sdk(user_text, agent_text, existing_topics))
    except Exception as e:
        _log(f"SDK call failed: {e}")
        return

    # Parse JSON from response, stripping markdown fences if present
    try:
        clean = response.strip()
        clean = re.sub(r"^```\w*\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
        result = json.loads(clean.strip())
    except json.JSONDecodeError as e:
        _log(f"JSON parse failed: {e}\nResponse: {response[:500]}")
        return

    with open_db() as conn:
        # Ensure session row exists before writing session-scoped data
        if session_id:
            ensure_session(conn, session_id)

        # Facts
        facts = result.get("facts", [])
        stored = store_facts(conn, facts)

        # Sentiment
        sentiment = result.get("sentiment")
        if session_id and isinstance(sentiment, str):
            store_sentiment(conn, session_id, sentiment, expected_content=agent_text)

        # Topics
        topics = result.get("topics", [])
        if session_id and isinstance(topics, list):
            store_topics(conn, session_id, topics)

        # Action items
        action_items = result.get("action_items", [])
        if session_id and isinstance(action_items, list) and action_items:
            store_action_items(conn, session_id, action_items, expected_content=agent_text)

        conn.commit()

    if stored:
        _log(f"Stored {stored} fact(s)")

    extras = []
    if result.get("sentiment"):
        extras.append(f"sentiment={result['sentiment']}")
    if result.get("topics"):
        extras.append(f"topics={result['topics']}")
    if result.get("action_items"):
        extras.append(f"actions={len(result['action_items'])}")
    if extras:
        _log(f"Extraction: {', '.join(extras)}")


if __name__ == "__main__":
    main()
