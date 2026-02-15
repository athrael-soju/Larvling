# Larvling

A self-bootstrapping Claude Code project scaffold. Three seed files grow into a full project.

## The 3 Seed Files

| File | Role |
|------|------|
| `.claude/settings.json` | Hook wiring + permissions |
| `scripts/preflight.py` | SessionStart hook: detects first run, creates audit DB on the spot, feeds bootstrap context |
| `CLAUDE.md` | Stable operating instructions — mode detection, session protocol, capabilities |
| `DNA.md` | The genome — interview questions + generation blueprint |

## Bootstrap Flow

```
Clone → first `claude` session
  │
  ├─ preflight.py fires, no DB found
  │   └─ Creates minimal DB with audit table → auditing from message 1
  │   └─ Outputs "BOOTSTRAP MODE" context
  │
  ├─ Claude reads CLAUDE.md → detects bootstrap mode → loads DNA.md
  │   └─ Interviews user (name, project type, what to track, work style...)
  │
  └─ Generates based on answers:
      ├─ Full DB schema (extends audit-only seed)
      ├─ Hook scripts (stop audit, guard, session context, archive)
      ├─ Slash commands (/plan, /log, /status or whatever fits)
      ├─ Rewritten CLAUDE.md (project-specific rules)
      └─ Dashboard scaffolding (optional)
```

## After Bootstrap

Preflight detects bootstrap is complete → introspects the DB dynamically and injects session context. The 3-file repo is now a full project. Every exchange audited from the very first message.

The key insight: `DNA.md` is the genome. The interview questions and generation templates live there. `CLAUDE.md` is the stable operating layer. The preflight script is just the trigger. The agent reads its own DNA and builds itself.
