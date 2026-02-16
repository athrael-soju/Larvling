---
name: summarize
description: Generate a session summary for a Larvling session
arguments:
  - name: session
    description: "Session ID (short or full). Use 'list' to see available sessions."
    required: false
---

Generate a session summary for a Larvling conversation session. You are the summarizer — read the conversation data and produce the summary yourself.

## Instructions

### Step 1: Session selection

If the user passed `list` as the session argument, or no argument at all, run:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" --list
```
Show the results so the user can pick a session. Sessions marked `[summarized]` already have a session summary — the user can choose to regenerate.

### Step 2: Check for existing summary

Once you have a session ID, check if a summary already exists:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --get
```
If one exists, show it and ask if the user wants to regenerate or keep it.

### Step 3: Ask scope

Ask the user what scope to summarize:
- **Whole session** — summarize all exchanges
- **Latest N exchanges** — summarize only the last N user/agent pairs

### Step 4: Fetch conversation pairs

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --pairs
```
Or for latest N:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --pairs --last N
```

This returns JSON with user/agent message pairs.

### Step 5: Incremental summarization

Do NOT try to summarize everything at once. Use this incremental approach:

1. **First pass — pair summaries**: For each user/agent pair, write a 1-2 sentence summary capturing what was discussed and what was accomplished.

2. **Second pass — combine**: Take the pair summaries and combine them into groups of 3-5. Summarize each group into a paragraph.

3. **Final pass**: Combine all group summaries into one cohesive session summary. It should cover:
   - What the user wanted to accomplish
   - Key decisions made
   - What was built, fixed, or changed
   - Any unresolved items or next steps

For small sessions (5 or fewer pairs), you can skip straight to the final summary.

### Step 6: Format and store the summary

Prepend a metadata header to the summary before storing. The header should describe what the summary covers:

- For **whole session**: `[Scope: full session | N exchanges]`
- For **latest N**: `[Scope: latest N of M exchanges]`

Example stored summary:
```
[Scope: full session | 28 exchanges]

The user implemented three major features for the Larvling plugin...
```

Store the final summary in the database:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --store "YOUR FORMATTED SUMMARY HERE"
```

The summary will appear in the dashboard sidebar and be used for context injection. Sessions with summaries show a download icon in the dashboard that lets the user save it to a file.

Tell the user the summary has been saved and what scope it covers.
