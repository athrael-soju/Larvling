---
name: loop
description: Start an iteration loop that blocks Claude from exiting until the task is complete
arguments:
  - name: prompt
    description: "The task prompt to iterate on. Flags: --max-iterations N, --completion-promise TEXT"
    required: true
---

Start a self-referential iteration loop. Claude will be blocked from exiting and the prompt will be re-fed each iteration, letting Claude see its previous work in files and git.

**CRITICAL RULE:** Do NOT output a false completion promise. The `<promise>` tag must reflect genuine task completion, not a shortcut to end the loop.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" start $ARGUMENTS
```
