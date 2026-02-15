The 3 Seed Files
File	Role
.claude/settings.json	Hook wiring + permissions
scripts/preflight.py	SessionStart hook: detects first run, creates audit DB on the spot, feeds bootstrap context
CLAUDE.md	The genome — interview questions + generation blueprint
Bootstrap Flow
Clone → first `claude` session
  │
  ├─ preflight.py fires, no DB found
  │   └─ Creates minimal DB with audit table → auditing from message 1
  │   └─ Outputs "bootstrap mode" context
  │
  ├─ Claude reads CLAUDE.md genome
  │   └─ Interviews user (name, project type, what to track, work style...)
  │
  └─ Generates based on answers:
      ├─ Full DB schema (extends audit-only seed)
      ├─ Hook scripts (stop audit, guard, session context, archive)
      ├─ Slash commands (/plan, /log, /status or whatever fits)
      ├─ Rewritten CLAUDE.md (project-specific)
      └─ Dashboard scaffolding (optional)

After Bootstrap
Preflight detects DB exists → injects normal session context. The 3-file repo is now a full project. Every exchange audited from the very first message.

The key insight: CLAUDE.md is the DNA. The interview questions and generation templates live there. The preflight script is just the trigger. The agent reads its own genome and builds itself.

Want me to start building this inside a zergling/ subdirectory here, or set it up as its own repo?