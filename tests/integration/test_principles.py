"""Principle tests — enforce the 6 Principles of Larvling as automated invariants."""

import os
import sqlite3
import unittest

from conftest import (
    SCRIPTS_DIR, PLUGIN_DIR, STDLIB_MODULES, PLATFORM_SPECIFIC_APIS,
    NETWORK_MODULES, AGENT_SCRIPTS, get_plugin_files,
)


class TestPrinciples(unittest.TestCase):

    def test_total_size_under_150kb(self):
        """Principle 1: Tiny — under 150 KB."""
        total = sum(os.path.getsize(f) for f in get_plugin_files())
        self.assertLess(
            total, 153600,
            f"Plugin is {total} bytes ({total/1024:.1f} KB), exceeds 150 KB limit"
        )

    def test_zero_dependencies(self):
        """Principle 2: Zero dependencies — only stdlib imports (agent scripts exempt)."""
        py_files = [f for f in get_plugin_files() if f.endswith(".py")]
        violations = []
        for path in py_files:
            basename = os.path.basename(path)
            if basename in AGENT_SCRIPTS:
                continue
            with open(path, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line.startswith(("import ", "from ")):
                        continue
                    if line.startswith("from "):
                        module = line.split()[1].split(".")[0]
                    else:
                        module = line.split()[1].split(".")[0].rstrip(",")
                    if module in ("db", "hooks", "preflight", "dashboard",
                                  "loop", "summarize", "export", "query",
                                  "transcript", "hook_prompt", "hook_stop",
                                  "hook_end", "hook_facts", "hook_summary",
                                  "subagent", "facts", "status"):
                        continue
                    if module not in STDLIB_MODULES:
                        violations.append(f"{basename}:{lineno} imports '{module}'")
        self.assertEqual(violations, [], f"Non-stdlib imports found:\n" + "\n".join(violations))

    def test_portable_no_platform_apis(self):
        """Principle 3: Portable — no platform-specific APIs."""
        py_files = [f for f in get_plugin_files() if f.endswith(".py")]
        violations = []
        for path in py_files:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            for api in PLATFORM_SPECIFIC_APIS:
                if api in content:
                    violations.append(f"{os.path.basename(path)} uses '{api}'")
        self.assertEqual(violations, [], f"Platform-specific APIs found:\n" + "\n".join(violations))

    def test_private_no_network_in_hooks(self):
        """Principle 4: Private — core hook files and db.py have no network imports."""
        for filename in ("hook_prompt.py", "hook_stop.py", "hook_end.py",
                         "transcript.py", "db.py"):
            path = os.path.join(SCRIPTS_DIR, filename)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            for mod in NETWORK_MODULES + ["urllib"]:
                self.assertNotIn(
                    f"import {mod}", content,
                    f"{filename} imports network module '{mod}'"
                )

    def test_instant_schema_no_config(self):
        """Principle 5: Instant — schema creates without any prior config."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        from db import create_schema
        create_schema(conn)
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        conn.close()
        for t in ("sessions", "messages", "facts", "loops"):
            self.assertIn(t, tables)

    def test_lightweight_wal_mode(self):
        """Principle 6: Lightweight — WAL mode is set on connections."""
        path = os.path.join(SCRIPTS_DIR, "db.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("PRAGMA journal_mode=WAL", content)

    def test_no_single_file_over_35kb(self):
        """Guard rail: no single file should exceed 35 KB."""
        for path in get_plugin_files():
            size = os.path.getsize(path)
            self.assertLess(
                size, 35840,
                f"{os.path.relpath(path, PLUGIN_DIR)} is {size} bytes ({size/1024:.1f} KB)"
            )
