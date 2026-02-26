"""Stop hook — logs the agent's last response and tracks token usage."""

from db import (
    open_db,
    ensure_session,
    record_message,
    store_message_metadata,
    read_hook_payload,
    log,
)
from transcript import parse_last_turn, wait_for_transcript_stable


def handle(data):
    if data.get("stop_hook_active"):
        return  # Prevent recursive hook firing

    session_id = data.get("session_id")
    if not session_id:
        return

    transcript_path = data.get("transcript_path")

    wait_for_transcript_stable(transcript_path)

    response, tools, usage = parse_last_turn(transcript_path)

    with open_db() as conn:
        ensure_session(conn, session_id)

        # Log the response (if any and not a duplicate)
        is_dup = False
        if response:
            row = conn.execute(
                "SELECT content FROM messages "
                "WHERE session_id = ? AND role = 'assistant' "
                "ORDER BY id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            is_dup = bool(row and row[0] == response)
            if not is_dup:
                meta = {"tool_calls": tools} if tools else {}
                if usage:
                    meta["usage"] = usage
                record_message(conn, session_id, "assistant", response, meta or None)
            elif usage:
                # Response was a dup (already stored), but still attach usage
                store_message_metadata(
                    conn,
                    session_id,
                    "assistant",
                    "usage",
                    usage,
                    expected_content=response,
                )

        conn.commit()

    # Log response details as JSONL
    resp_data = {"chars": len(response) if response else 0, "is_dup": is_dup}
    if tools:
        resp_data["tools"] = sum(tools.values())
    if usage:
        cached = usage.get("cache_read_input_tokens", 0)
        if cached:
            resp_data["cache_read"] = cached
        new_in = usage.get("input_tokens", 0) + usage.get(
            "cache_creation_input_tokens", 0
        )
        if new_in:
            resp_data["input_new"] = new_in
        agent_out = usage.get("output_tokens", 0)
        if agent_out:
            resp_data["output"] = agent_out
        if usage.get("output_tokens_estimated"):
            resp_data["output_estimated"] = True

    log("response", session_id, **resp_data)


if __name__ == "__main__":
    data = read_hook_payload()
    if data:
        handle(data)
