# Changelog

## [0.1.5] - 2026-02-26

### Added
- `maxTurns: 10` on agents to prevent runaway execution
- `knowledge-maintenance` agent and `/maintain` skill for periodic knowledge base audit and consolidation
- `busy_timeout` PRAGMA for SQLite lock resilience
- `stop_hook_active` check in Stop hook to prevent recursive firing
- 24h file-based cache for geolocation and update check HTTP calls
- SessionStart matcher differentiation (skips context on compact events)
- Graceful `ImportError` handling for `claude_agent_sdk` dependency
- `PYTHONPATH` in hook commands (replaces fragile `sys.path` manipulation)
- `author`, `repository`, `license`, `keywords` in plugin manifest
- `requirements.txt` for dependency declaration
- `LICENSE` (MIT)

### Changed
- Stop hook timeout increased from 5s to 15s
- Stop hook chain uses `;` between `stop.py` and `analyze.py` (independent ops)
- Agent model overrides consolidated to `settings.json` (removed from frontmatter)

### Removed
- `sys.path.insert` hacks from hook scripts (replaced by PYTHONPATH)
