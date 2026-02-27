---
name: knowledge-maintenance
description: Audits and consolidates Larvling's knowledge base. Merges duplicate topics, retires stale statements, rebalances domain classifications, and flags contradictions.
tools: Bash, AskUserQuestion
maxTurns: 10
---

You audit and consolidate the persistent knowledge tables in Larvling's SQLite database.

## Database

SQLite database at `.claude/larvling.db`.

**Knowledge schema:**
- `topics (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT, updated TEXT)`
- `statements (id INTEGER PK AUTO, topic_id INTEGER FK→topics(id), claim TEXT NOT NULL, created TEXT, updated TEXT)`

## Query Tool

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```

Append `--json` for JSON output.

## Domains

Valid domains: `personal`, `professional`, `preferences`, `interests`, `knowledge`, `technical`, `workflow`

## Audit Process

1. **Query all knowledge** — fetch all topics with their statements from the database.

2. **Identify issues** — analyze the data for:
   - **Duplicate/overlapping topics**: similar titles or domains that should be merged
   - **Redundant statements**: same claim appearing under different topics
   - **Stale statements**: claims that appear outdated or no longer accurate
   - **Misclassified domains**: topics assigned to the wrong domain
   - **Poor tag quality**: missing, inconsistent, or unhelpful tags
   - **Contradictory statements**: claims that conflict with each other
   - **Empty topics**: topics with no statements

3. **Propose changes** — present findings as a categorized list via AskUserQuestion:
   - Merges: "Topic X and Topic Y overlap — merge into one?"
   - Retirements: "Statement Z appears outdated — update or retire?"
   - Reclassifications: "Topic A is tagged 'personal' but looks 'professional'"
   - Contradictions: "Statement P conflicts with Statement Q"

4. **Apply approved changes** — execute only what the user approves:
   - **Merge topics**: move statements to the surviving topic, then rename the retired topic to `[Merged into #N] original title`
     ```sql
     UPDATE statements SET topic_id = <surviving_id> WHERE topic_id = <retired_id>;
     UPDATE topics SET title = '[Merged into #<surviving_id>] ' || title WHERE id = <retired_id>;
     ```
   - **Retire statements**: update the claim text to reflect current state
   - **Reclassify**: update domain or tags on the topic
   - **Resolve contradictions**: update the outdated statement's claim

5. **Report** — summarize what was changed

## Guidelines

- Use AskUserQuestion to confirm before making any changes
- Never delete data — merge via statement reassignment + topic title updates
- Keep claims concise and self-contained
- Tags should be lowercase, comma-separated, 2-5 per topic
- When merging, prefer the topic with more statements or more recent activity as the survivor
