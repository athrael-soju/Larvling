---
name: loop
description: "Start an autonomous iteration loop with fresh context per cycle. Use `/loop cancel` to shut down, `/loop status` to check progress."
arguments:
  - name: prompt
    description: "The task description, 'cancel' to shut down, or 'status' to check progress. Flags: --max-iterations N"
    required: true
---

Run this in the background (it may take a while):

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/loop.sh" $ARGUMENTS
```

Each iteration spawns a fresh agent that reads/writes Larvling's fact store for cross-iteration memory. Agents can spawn teams within an iteration for parallel sub-work.

Report progress to the user when the loop finishes or is cancelled.
