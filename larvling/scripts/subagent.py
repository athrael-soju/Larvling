"""Shared helper for spawning claude -p subagents."""

import os
import subprocess
import sys


def spawn_agent(prompt, cwd=None, model="haiku", max_turns=6):
    """Spawn a claude -p subagent and print its output."""
    env = os.environ.copy()
    env["LARVLING_AGENT"] = "1"
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", model,
         "--dangerously-skip-permissions", "--max-turns", str(max_turns)],
        capture_output=True, text=True, env=env,
        cwd=cwd or os.getcwd(),
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
