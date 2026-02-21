"""
Unified extraction via Claude Agent SDK.

Called as a Stop command hook. Reads the transcript, extracts the last
exchange, calls Sonnet to identify facts, sentiment, topics, and action
items in a single SDK call, then writes results to SQLite.
"""

import asyncio
import json
import os
import sys
import time

from db import open_db, has_table, parse_meta, reconfigure_stdout, ensure_session

# Import parse_last_turn from hooks.py (also extracts tool counts)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hooks import parse_last_turn, wait_for_transcript_stable

# ---------------------------------------------------------------------------
# Transcript parsing — extract user text from the last exchange
# ---------------------------------------------------------------------------


def _is_real_user_message(entry):
    if entry.get("type") != "user":
        return False
    msg = entry.get("message", {})
    if not isinstance(msg, dict):
        return False
    content = msg.get("content", "")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return False
        return True
    return False


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

3. **topics** - Short topic labels for what was discussed (1-4 words each)

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


async def call_sdk(user_text, agent_text):
    """Call Sonnet via Agent SDK to extract facts, sentiment, topics, action items."""
    from claude_code_sdk import query, ClaudeCodeOptions

    prompt = EXTRACTION_PROMPT.format(
        user_text=user_text or "(no user text)",
        agent_text=(agent_text or "(no agent text)")[:2000],
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
        "SELECT id FROM facts ORDER BY CAST(SUBSTR(id, 3) AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    if row:
        try:
            num = int(row["id"].split("-")[1])
            return num + 1
        except (IndexError, ValueError):
            pass
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


def store_sentiment(conn, session_id, sentiment):
    """Store sentiment in the metadata of the last assistant message."""
    if not sentiment:
        return

    row = conn.execute(
        "SELECT id, metadata FROM messages "
        "WHERE session_id = ? AND role = 'assistant' "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row:
        return

    meta = parse_meta(row["metadata"])
    meta["sentiment"] = sentiment
    conn.execute(
        "UPDATE messages SET metadata = ? WHERE id = ?",
        (json.dumps(meta), row["id"]),
    )


def store_topics(conn, session_id, topics):
    """Accumulate topics into sessions.topics (comma-separated, deduplicated)."""
    if not topics:
        return

    row = conn.execute(
        "SELECT topics FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        return

    existing = set()
    if row["topics"]:
        existing = {t.strip().lower() for t in row["topics"].split(",") if t.strip()}

    new_topics = []
    for t in topics:
        t_clean = str(t).strip()
        if t_clean and t_clean.lower() not in existing:
            new_topics.append(t_clean)
            existing.add(t_clean.lower())

    if not new_topics:
        return

    all_topics = row["topics"] or ""
    if all_topics:
        all_topics += ", " + ", ".join(new_topics)
    else:
        all_topics = ", ".join(new_topics)

    conn.execute(
        "UPDATE sessions SET topics = ? WHERE id = ?",
        (all_topics, session_id),
    )


def store_action_items(conn, session_id, action_items):
    """Store action items in the metadata of the last assistant message."""
    if not action_items:
        return

    row = conn.execute(
        "SELECT id, metadata FROM messages "
        "WHERE session_id = ? AND role = 'assistant' "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row:
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
    except Exception:
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

    try:
        response = asyncio.run(call_sdk(user_text, agent_text))
    except Exception as e:
        _log_error(f"SDK call failed: {e}")
        return

    # Parse JSON from response
    try:
        clean = response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        result = json.loads(clean.strip())
    except json.JSONDecodeError as e:
        _log_error(f"JSON parse failed: {e}\nResponse: {response[:500]}")
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
            store_sentiment(conn, session_id, sentiment)

        # Topics
        topics = result.get("topics", [])
        if session_id and isinstance(topics, list):
            store_topics(conn, session_id, topics)

        # Action items
        action_items = result.get("action_items", [])
        if session_id and isinstance(action_items, list) and action_items:
            store_action_items(conn, session_id, action_items)

        conn.commit()

    if stored:
        _log_error(f"Stored {stored} fact(s)")

    extras = []
    if result.get("sentiment"):
        extras.append(f"sentiment={result['sentiment']}")
    if result.get("topics"):
        extras.append(f"topics={result['topics']}")
    if result.get("action_items"):
        extras.append(f"actions={len(result['action_items'])}")
    if extras:
        _log_error(f"Extraction: {', '.join(extras)}")


def _log_error(msg):
    try:
        log_path = os.path.join(os.getcwd(), ".claude", "larvling-errors.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
