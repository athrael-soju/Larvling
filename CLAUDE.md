# Zergling Genome

> You are reading your own DNA. This file drives bootstrap on first run
> and becomes the project's operating manual after generation.

---

## Mode Detection

When your SessionStart hook (`scripts/preflight.py`) fires:

- **"BOOTSTRAP MODE"** → Start from Phase 1 (audit table already created by preflight).
- **"BOOTSTRAP INCOMPLETE"** → Resume bootstrap. Check the audit table for what was already completed.
- Otherwise → You are in a live project. Follow the Project Rules section (generated during bootstrap).

---

## Bootstrap Protocol

### Auditing

The `preflight.py` hook creates the audit table and logs `bootstrap_start` before you receive any input. The audit table is ready — **log every action from your very first message**: interview questions, user answers, generation steps, errors, completions.

```sql
INSERT INTO audit (event_type, content) VALUES ('<event>', '<description>');
```

### Phase 1 — Interview

Ask these questions **conversationally** — adapt based on answers, skip what's obvious, dig deeper where it matters. Don't dump them as a list.

#### Identity
1. What's the project called?
2. One-line description — what does it do?
3. Language / stack / framework?

#### What to Track
4. What matters to you? Pick any that apply, or add your own:
   - **Tasks** (todos, backlog, sprints)
   - **Decisions** (architectural choices with rationale)
   - **Bugs** (issues, repro steps, status)
   - **Ideas** (parking lot for future work)
   - **Time** (session duration, work logs)
   - **Context** (key files, architecture notes, domain knowledge)
5. Anything else you want the system to remember between sessions?

#### Work Style
6. Solo or team?
7. Do you want approval gates before risky operations (destructive git, DB migrations, deploys)?
8. Auto-commit preference? (never / after milestones / always)

#### Assistant Personality
9. Terse or verbose? (e.g., "just the code" vs. explanations)
10. Any naming conventions, patterns, or project rules I should enforce?

### Phase 2 — Generate

Once you have answers, generate **all** of the following in a single pass. Do not ask for confirmation between components — build the whole thing, then present a summary.

#### 2a. Extend the Database

The audit table was created by preflight. Now add tables based on what the user wants to track. Every table must include:
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `created_at TEXT NOT NULL DEFAULT (datetime('now'))`
- `updated_at TEXT`

Create tables directly in `.claude/zergling.db` using `CREATE TABLE IF NOT EXISTS`. No migration framework — Claude can inspect and alter the live schema when changes are needed later.

Common table patterns (use only what's needed):

| Tracking choice | Tables to create |
|---|---|
| Tasks | `tasks` (title, status, priority, tags, assigned_to, due_date) |
| Decisions | `decisions` (title, rationale, status, alternatives, outcome) |
| Bugs | `bugs` (title, severity, repro_steps, status, resolution) |
| Ideas | `ideas` (title, description, tags, status) |
| Time | `sessions` (start_time, end_time, duration_min, summary) |
| Context | `context` (key, value, category, notes) |

#### 2b. Hook Scripts (`scripts/`)

Generate these hook scripts based on user preferences:

| Script | Hook Event | Purpose |
|---|---|---|
| `scripts/preflight.py` | SessionStart | Already exists — update to inject richer context from new tables |
| `scripts/audit_stop.py` | Stop | Log session summary, token usage, decisions made |
| `scripts/guard.py` | PreToolUse | Block risky operations if user wants approval gates |
| `scripts/session_end.py` | SessionEnd | Archive session, update time tracking |

Only generate `guard.py` if user wants approval gates. Keep each script focused and under 100 lines.

#### 2c. Slash Commands (`.claude/commands/`)

Generate markdown command files. Each command should be a `.md` file with a clear prompt.

Minimum set:
- `/status` — Show project state: open tasks, recent decisions, session stats
- `/log` — Quick-add an entry (task, bug, idea, decision) via natural language

Additional commands based on tracking choices:
- `/plan` — Break work into tasks, estimate scope (if Tasks enabled)
- `/decide` — Record an architectural decision with rationale (if Decisions enabled)
- `/review` — Summarize what happened this session (if Time enabled)

#### 2d. Rewrite This File

Replace everything below the `---` line in this file with project-specific content:

```
# <Project Name>

## Project Overview
<one-liner and stack>

## Architecture
<key files, entry points, patterns — filled in as discovered>

## Conventions
<naming, commit style, code patterns the user specified>

## Session Protocol
- On session start, review the context injected by preflight
- Check /status for current state
- Log decisions and progress as you work
- On session end, audit_stop.py captures the summary

## Commands
<list generated slash commands and what they do>

## Rules
<any constraints the user specified>
```

#### 2e. Dashboard (Optional)

If the user wants visibility into their tracked data, generate a simple `scripts/dashboard.py` that:
- Queries the SQLite DB
- Prints a formatted terminal dashboard (task counts, recent activity, session stats)
- Can be run standalone or wired to a slash command

### Phase 3 — Finalize

After generation:
1. Log completion to the audit table:
   ```sql
   INSERT INTO audit (event_type, content) VALUES ('bootstrap_complete', 'Bootstrap finished — all components generated');
   ```
2. Run `python scripts/preflight.py` to confirm it exits bootstrap mode and shows session context
3. Present a summary of everything created to the user

---

## Project Rules

*This section will be replaced during bootstrap with project-specific rules.*

---
