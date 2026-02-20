---
name: loop
description: "Orchestrate a complex task using a team of parallel workers. Use `/loop cancel` to shut down the team."
arguments:
  - name: prompt
    description: "The task description, or 'cancel' to shut down the active team"
    required: true
---

You are orchestrating a complex task using Claude Code's native team system. Follow these steps precisely.

## If the argument is "cancel"

Shut down the active team:
1. Read the team config to find all teammates
2. Send `shutdown_request` to each teammate via `SendMessage`
3. Clean up with `TeamDelete`
4. Confirm to the user that the team has been shut down

## Otherwise — start a new team

### 1. Create the team

```
TeamCreate with team_name: "larvling-task"
```

### 2. Decompose the task

Break the user's prompt into independent sub-tasks. Each sub-task should be:
- Self-contained (can be completed without waiting on other tasks)
- Clearly scoped with acceptance criteria
- Small enough for a single agent to handle

Create tasks with `TaskCreate` for each sub-task.

### 3. Spawn workers

For each sub-task, spawn a worker agent:

```
Task tool with:
  subagent_type: "general-purpose"
  team_name: "larvling-task"
  name: "worker-N"  (numbered sequentially)
  prompt: "<the sub-task description with full context>"
```

Spawn workers in parallel when their tasks are independent.

### 4. Coordinate

- Monitor progress via `TaskList` and teammate messages (delivered automatically)
- Assign new tasks as workers complete their current ones
- Handle blockers by reassigning or adjusting the plan
- Use `SendMessage` to give workers additional context when needed

### 5. Verify and wrap up

Once all tasks are complete:
1. Review the completed work yourself
2. Send `shutdown_request` to all workers
3. Clean up with `TeamDelete`
4. Report results to the user
