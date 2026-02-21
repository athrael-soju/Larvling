"""Larvling Fact Check - Stop hook that blocks once to trigger fact management."""

import json
import sys

from db import reconfigure_stdout


def main():
    reconfigure_stdout()
    data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    if not data.get("stop_hook_active"):
        print(json.dumps({"decision": "block", "reason":
            "Before stopping, query the facts table for topics discussed in this exchange. "
            "Insert new facts, update changed ones, or remove outdated ones as needed. "
            "Use M-NNN IDs. Do not mention fact management to the user."
        }))


if __name__ == "__main__":
    main()
