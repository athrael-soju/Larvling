---
name: loop
description: "Start an autonomous iteration loop with optional team orchestration. Use `/loop cancel` to shut down."
arguments:
  - name: prompt
    description: "The task description, or 'cancel' to shut down"
    required: true
---

You are starting an autonomous iteration loop inspired by [Ralph](https://github.com/snarktank/ralph). Each iteration spawns a fresh agent with clean context. Progress persists through Larvling's DB memory (`/query` against larvling.db).

## If the argument is "cancel"

Shut down the active loop:
1. If a team is active, send `shutdown_request` to each teammate via `SendMessage`, then `TeamDelete`
2. Clean up loop facts: `/query "DELETE FROM facts WHERE domain = 'loop'"`
3. Confirm to the user that the loop has been shut down

## Otherwise — start a loop

### 1. Decompose the task

Break the prompt into discrete stories/sub-tasks. For each story, create a fact tracking its status:

```
/query "INSERT INTO facts (id, claim, domain, tags, source) VALUES ('L-001', 'Story: <description> | Status: pending', 'loop', 'loop,story', 'loop')"
```

### 2. Choose orchestration mode

**Serial (default):** Work through stories one at a time, highest priority first. After completing each story:
- Run quality checks (typecheck, lint, test — whatever the project uses)
- Update the story fact status to `done`
- Record learnings as facts for future iterations
- Do NOT commit — the user will commit when ready

**Parallel (for independent stories):** If stories are independent, use Claude Code's team system:
1. `TeamCreate` with team_name `"larvling-loop"`
2. `TaskCreate` for each story
3. Spawn `general-purpose` workers via `Task` tool with `team_name: "larvling-loop"`
4. Coordinate via `TaskList`/`TaskUpdate`/`SendMessage`
5. When all tasks complete, shut down workers and `TeamDelete`

### 3. Larvling DB as cross-iteration memory

Larvling's fact store is the shared memory across iterations and workers. Use `/query` for all DB operations.

**Before starting work**, read the current state:
```
/query "SELECT id, claim FROM facts WHERE domain = 'loop' ORDER BY id"
```

**During work**, store discoveries, decisions, and context:
```
/query "INSERT INTO facts (id, claim, domain, tags, source) VALUES ('L-<id>', '<insight>', 'loop', 'loop,learning', 'loop')"
```

**Types of facts to store:**
- **Stories** (tag: `loop,story`): Task descriptions with status (`pending` / `in-progress` / `done` / `blocked`)
- **Learnings** (tag: `loop,learning`): Patterns discovered, gotchas, conventions found during implementation
- **Blockers** (tag: `loop,blocker`): Issues preventing progress, with context for the next iteration
- **Decisions** (tag: `loop,decision`): Architectural choices made and why, so future iterations don't revisit them

**Update facts** as knowledge evolves — don't just append, refine:
```
/query "UPDATE facts SET claim = '<updated insight>' WHERE id = 'L-<id>'"
```

**For parallel workers:** Each worker should read facts before starting and write facts when done. This is how workers share context without direct communication.

### 4. Iteration protocol

For each story:
1. Read ALL loop facts: `/query "SELECT id, claim FROM facts WHERE domain = 'loop' ORDER BY id"`
2. Pick the highest priority story where status is `pending`
3. Check for relevant learnings/decisions from previous iterations
4. Implement that single story
5. Run quality checks
6. Update the story fact status to `done`
7. Record any learnings, patterns, or gotchas discovered as new facts

### 5. Completion

After completing a story, check if ALL stories are done:
```
/query "SELECT id, claim FROM facts WHERE domain = 'loop' AND tags LIKE '%story%' AND claim NOT LIKE '%done%'"
```

If no pending stories remain, the loop is complete. Report results to the user.

### 6. Rules

- Work on ONE story per iteration (serial mode) or ONE story per worker (parallel mode)
- Always read loop facts before starting work — they are your memory
- Always write learnings after completing work — they are the next iteration's memory
- NEVER commit changes — the user will commit when ready
- Follow existing code patterns
- If blocked, create a blocker fact and move to the next story
