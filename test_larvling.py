"""Comprehensive test suite for Larvling plugin.

Tests the 6 Principles as automated invariants, core database operations,
hook event handling, context injection, and dashboard rendering.
"""

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

# Add scripts dir to path so we can import modules
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "larvling", "scripts")
sys.path.insert(0, SCRIPTS_DIR)

PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "larvling")

# Known Python stdlib modules (subset covering what Larvling uses + common ones)
STDLIB_MODULES = {
    "os", "sys", "json", "re", "time", "sqlite3", "shutil", "subprocess",
    "urllib", "urllib.request", "html", "io", "tempfile", "unittest",
    "contextlib", "pathlib", "datetime", "collections", "functools",
    "itertools", "hashlib", "math", "string", "textwrap", "copy",
    "typing", "abc", "enum", "dataclasses", "argparse", "logging",
}

# Platform-specific APIs that violate portability
PLATFORM_SPECIFIC_APIS = [
    "os.startfile", "winreg", "msvcrt", "_winapi",
    "resource", "grp", "pwd", "fcntl", "termios",
]

# Network modules that should not appear in runtime hooks
NETWORK_MODULES = ["requests", "httpx", "aiohttp", "websocket"]


def make_db():
    """Create a fresh in-memory database with schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    from db import create_schema
    create_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Principle Tests
# ---------------------------------------------------------------------------


class TestPrinciples(unittest.TestCase):
    """Enforce the 6 Principles of Larvling as automated invariants."""

    def _get_plugin_files(self):
        """Get all files in larvling/ excluding __pycache__."""
        files = []
        for root, dirs, filenames in os.walk(PLUGIN_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in filenames:
                files.append(os.path.join(root, f))
        return files

    def test_total_size_under_150kb(self):
        """Principle 1: Tiny — under 150 KB (relaxed while dashboard template is unoptimized)."""
        total = sum(os.path.getsize(f) for f in self._get_plugin_files())
        self.assertLess(
            total, 153600,
            f"Plugin is {total} bytes ({total/1024:.1f} KB), exceeds 150 KB limit"
        )

    def test_zero_dependencies(self):
        """Principle 2: Zero dependencies — only stdlib imports."""
        py_files = [f for f in self._get_plugin_files() if f.endswith(".py")]
        violations = []
        for path in py_files:
            with open(path, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line.startswith(("import ", "from ")):
                        continue
                    if line.startswith("from "):
                        module = line.split()[1].split(".")[0]
                    else:
                        module = line.split()[1].split(".")[0].rstrip(",")
                    # Skip relative imports within the plugin
                    if module in ("db", "hooks", "preflight", "dashboard",
                                  "loop", "summarize", "export", "query"):
                        continue
                    if module not in STDLIB_MODULES:
                        violations.append(f"{os.path.basename(path)}:{lineno} imports '{module}'")
        self.assertEqual(violations, [], f"Non-stdlib imports found:\n" + "\n".join(violations))

    def test_portable_no_platform_apis(self):
        """Principle 3: Portable — no platform-specific APIs."""
        py_files = [f for f in self._get_plugin_files() if f.endswith(".py")]
        violations = []
        for path in py_files:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            for api in PLATFORM_SPECIFIC_APIS:
                if api in content:
                    violations.append(f"{os.path.basename(path)} uses '{api}'")
        self.assertEqual(violations, [], f"Platform-specific APIs found:\n" + "\n".join(violations))

    def test_private_no_network_in_hooks(self):
        """Principle 4: Private — hooks.py and db.py have no network imports."""
        for filename in ("hooks.py", "db.py"):
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
        self.assertIn("sessions", tables)
        self.assertIn("messages", tables)
        self.assertIn("facts", tables)
        self.assertIn("loops", tables)

    def test_lightweight_wal_mode(self):
        """Principle 6: Lightweight — WAL mode is set on connections."""
        path = os.path.join(SCRIPTS_DIR, "db.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("PRAGMA journal_mode=WAL", content)

    def test_no_single_file_over_35kb(self):
        """Guard rail: no single file should exceed 35 KB."""
        for path in self._get_plugin_files():
            size = os.path.getsize(path)
            self.assertLess(
                size, 35840,
                f"{os.path.relpath(path, PLUGIN_DIR)} is {size} bytes ({size/1024:.1f} KB)"
            )


# ---------------------------------------------------------------------------
# Database CRUD Tests
# ---------------------------------------------------------------------------


class TestDatabaseCRUD(unittest.TestCase):
    """Test core database operations in db.py."""

    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def test_create_schema_idempotent(self):
        """Calling create_schema twice does not raise or corrupt."""
        from db import create_schema
        create_schema(self.conn)  # second call
        tables = [row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        self.assertEqual(len(tables), 4)

    def test_schema_has_all_tables(self):
        tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
        self.assertEqual(tables, {"sessions", "messages", "facts", "loops"})

    def test_schema_has_indexes(self):
        indexes = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
        self.assertIn("idx_messages_session", indexes)
        self.assertIn("idx_loops_session", indexes)
        self.assertIn("idx_loops_status", indexes)

    def test_ensure_session_creates(self):
        from db import ensure_session
        ensure_session(self.conn, "sess-001")
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM sessions WHERE id = 'sess-001'").fetchone()
        self.assertIsNotNone(row)
        self.assertIsNotNone(row["started_at"])

    def test_ensure_session_upserts(self):
        from db import ensure_session
        ensure_session(self.conn, "sess-001")
        self.conn.commit()
        first_started = self.conn.execute(
            "SELECT started_at FROM sessions WHERE id = 'sess-001'"
        ).fetchone()[0]
        ensure_session(self.conn, "sess-001")
        self.conn.commit()
        count = self.conn.execute("SELECT COUNT(*) FROM sessions WHERE id = 'sess-001'").fetchone()[0]
        self.assertEqual(count, 1)
        row = self.conn.execute("SELECT started_at FROM sessions WHERE id = 'sess-001'").fetchone()
        self.assertEqual(row[0], first_started)

    def test_record_message_basic(self):
        from db import ensure_session, record_message
        ensure_session(self.conn, "sess-001")
        record_message(self.conn, "sess-001", "user", "hello world")
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM messages WHERE session_id = 'sess-001'"
        ).fetchone()
        self.assertEqual(row["role"], "user")
        self.assertEqual(row["content"], "hello world")

    def test_record_message_with_metadata(self):
        from db import ensure_session, record_message
        ensure_session(self.conn, "sess-001")
        meta = {"tool_calls": {"Read": 3, "Write": 1}}
        record_message(self.conn, "sess-001", "assistant", "done", meta)
        self.conn.commit()
        row = self.conn.execute(
            "SELECT metadata FROM messages WHERE session_id = 'sess-001'"
        ).fetchone()
        parsed = json.loads(row["metadata"])
        self.assertEqual(parsed["tool_calls"]["Read"], 3)

    def test_record_summary_coalesce(self):
        """Only non-None fields overwrite existing values."""
        from db import ensure_session, record_summary
        ensure_session(self.conn, "sess-001")
        record_summary(self.conn, "sess-001", title="First title", agent_summary="Summary A")
        self.conn.commit()
        record_summary(self.conn, "sess-001", title="Updated title")
        self.conn.commit()
        row = self.conn.execute("SELECT title, agent_summary FROM sessions WHERE id = 'sess-001'").fetchone()
        self.assertEqual(row["title"], "Updated title")
        self.assertEqual(row["agent_summary"], "Summary A")

    def test_finalize_session(self):
        from db import ensure_session, finalize_session
        ensure_session(self.conn, "sess-001")
        self.conn.commit()
        finalize_session(self.conn, "sess-001")
        self.conn.commit()
        row = self.conn.execute("SELECT ended_at, duration_min FROM sessions WHERE id = 'sess-001'").fetchone()
        self.assertIsNotNone(row["ended_at"])
        self.assertIsNotNone(row["duration_min"])

    def test_get_summary_returns_row(self):
        from db import ensure_session, record_summary, get_summary
        ensure_session(self.conn, "sess-001")
        record_summary(self.conn, "sess-001", title="Test", agent_summary="A summary")
        self.conn.commit()
        row = get_summary(self.conn, "sess-001")
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "Test")
        self.assertEqual(row["agent_summary"], "A summary")

    def test_get_summary_missing(self):
        from db import get_summary
        row = get_summary(self.conn, "nonexistent")
        self.assertIsNone(row)

    def test_resolve_session_full_id(self):
        from db import ensure_session, resolve_session
        full_id = "abcdef01-2345-6789-abcd-ef0123456789"
        ensure_session(self.conn, full_id)
        self.conn.commit()
        result = resolve_session(self.conn, full_id)
        self.assertEqual(result, full_id)

    def test_resolve_session_short_id(self):
        from db import ensure_session, resolve_session
        full_id = "abcdef01-2345-6789-abcd-ef0123456789"
        ensure_session(self.conn, full_id)
        self.conn.commit()
        result = resolve_session(self.conn, "abcdef01")
        self.assertEqual(result, full_id)

    def test_resolve_session_no_match(self):
        from db import resolve_session
        result = resolve_session(self.conn, "zzzzz")
        self.assertIsNone(result)

    def test_escape_like(self):
        from db import escape_like
        self.assertEqual(escape_like("hello"), "hello")
        self.assertIn("\\%", escape_like("100%"))
        self.assertIn("\\_", escape_like("my_var"))
        self.assertIn("\\\\", escape_like("back\\slash"))

    def test_list_sessions_output(self):
        from db import ensure_session, record_summary, list_sessions
        ensure_session(self.conn, "sess-001")
        record_summary(self.conn, "sess-001", title="Test session")
        self.conn.commit()
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            list_sessions(self.conn)
        output = captured.getvalue()
        self.assertIn("sess-001", output)
        self.assertIn("Test session", output)

    def test_parse_meta_robustness(self):
        from db import parse_meta
        self.assertEqual(parse_meta(None), {})
        self.assertEqual(parse_meta(""), {})
        self.assertEqual(parse_meta("not json"), {})
        self.assertEqual(parse_meta('{"key": "val"}'), {"key": "val"})


# ---------------------------------------------------------------------------
# Hooks Event Handling Tests
# ---------------------------------------------------------------------------


class TestHooksEventHandling(unittest.TestCase):
    """Test hooks.py pure functions and event handlers."""

    def test_strip_ide_tags_basic(self):
        from hooks import strip_ide_tags
        text = '<ide_opened_file>/path/to/file.py</ide_opened_file> hello world'
        self.assertEqual(strip_ide_tags(text), "hello world")

    def test_strip_ide_tags_selection(self):
        from hooks import strip_ide_tags
        text = '<ide_selection>some selected text</ide_selection> actual prompt'
        self.assertEqual(strip_ide_tags(text), "actual prompt")

    def test_strip_ide_tags_multiple(self):
        from hooks import strip_ide_tags
        text = (
            '<ide_opened_file>file1.py</ide_opened_file> '
            '<ide_selection>sel</ide_selection> prompt here'
        )
        self.assertEqual(strip_ide_tags(text), "prompt here")

    def test_strip_ide_tags_preserves_content(self):
        from hooks import strip_ide_tags
        text = "just a normal prompt with no tags"
        self.assertEqual(strip_ide_tags(text), text)

    def test_strip_ide_tags_empty(self):
        from hooks import strip_ide_tags
        self.assertEqual(strip_ide_tags(""), "")

    def test_is_real_user_message_text(self):
        from hooks import _is_real_user_message
        entry = {"type": "user", "message": {"content": "hello"}}
        self.assertTrue(_is_real_user_message(entry))

    def test_is_real_user_message_tool_result(self):
        from hooks import _is_real_user_message
        entry = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}
        self.assertFalse(_is_real_user_message(entry))

    def test_is_real_user_message_non_user(self):
        from hooks import _is_real_user_message
        entry = {"type": "assistant", "message": {"content": "hi"}}
        self.assertFalse(_is_real_user_message(entry))

    def test_is_real_user_message_list_without_tool_result(self):
        from hooks import _is_real_user_message
        entry = {"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}
        self.assertTrue(_is_real_user_message(entry))

    def test_parse_last_turn_empty(self):
        from hooks import parse_last_turn
        text, tools = parse_last_turn(None)
        self.assertIsNone(text)
        self.assertEqual(tools, {})

    def test_parse_last_turn_nonexistent(self):
        from hooks import parse_last_turn
        text, tools = parse_last_turn("/nonexistent/path.jsonl")
        self.assertIsNone(text)
        self.assertEqual(tools, {})

    def test_parse_last_turn_simple(self):
        from hooks import parse_last_turn
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "do something"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "I did it"}]}}) + "\n")
            path = f.name
        try:
            text, tools = parse_last_turn(path)
            self.assertEqual(text, "I did it")
            self.assertEqual(tools, {})
        finally:
            os.unlink(path)

    def test_parse_last_turn_with_tools(self):
        from hooks import parse_last_turn
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "read file"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read"},
                {"type": "tool_use", "name": "Read"},
                {"type": "text", "text": "Here's the file"},
            ]}}) + "\n")
            path = f.name
        try:
            text, tools = parse_last_turn(path)
            self.assertEqual(text, "Here's the file")
            self.assertEqual(tools, {"Read": 2})
        finally:
            os.unlink(path)

    def test_parse_last_turn_skips_tool_results(self):
        """Tool result user messages should not be turn boundaries."""
        from hooks import parse_last_turn
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "do work"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Working..."}]}}) + "\n")
            f.write(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "file contents"}]}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "All done"}]}}) + "\n")
            path = f.name
        try:
            text, tools = parse_last_turn(path)
            self.assertIn("All done", text)
            self.assertIn("Working", text)
        finally:
            os.unlink(path)

    def test_handle_user_prompt_records(self):
        """handle_user_prompt records the message and sets title on first prompt."""
        import db
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            from db import create_schema
            create_schema(conn)
            conn.close()

            with mock.patch.object(db, "DB_PATH", test_db):
                from hooks import handle_user_prompt
                handle_user_prompt({
                    "session_id": "test-sess",
                    "prompt": "Build a feature",
                    "cwd": "/tmp",
                    "permission_mode": "default",
                })

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            msg = conn.execute("SELECT * FROM messages WHERE session_id = 'test-sess'").fetchone()
            self.assertIsNotNone(msg)
            self.assertEqual(msg["role"], "user")
            self.assertEqual(msg["content"], "Build a feature")
            sess = conn.execute("SELECT title FROM sessions WHERE id = 'test-sess'").fetchone()
            self.assertEqual(sess["title"], "Build a feature")
            conn.close()

    def test_handle_session_end_finalizes(self):
        import db
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            from db import create_schema, ensure_session, record_message
            create_schema(conn)
            ensure_session(conn, "test-sess")
            record_message(conn, "test-sess", "user", "hello")
            record_message(conn, "test-sess", "assistant", "hi")
            conn.commit()
            conn.close()

            with mock.patch.object(db, "DB_PATH", test_db):
                from hooks import handle_session_end
                handle_session_end({"session_id": "test-sess"})

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            sess = conn.execute("SELECT * FROM sessions WHERE id = 'test-sess'").fetchone()
            self.assertIsNotNone(sess["ended_at"])
            self.assertEqual(sess["exchange_count"], 1)
            conn.close()


# ---------------------------------------------------------------------------
# Preflight Context Tests
# ---------------------------------------------------------------------------


class TestPreflightContext(unittest.TestCase):
    """Test preflight.py context generation functions."""

    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def test_ensure_schema_fresh_install(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from preflight import ensure_schema
                result = ensure_schema()
            self.assertEqual(result, "fresh")

    def test_ensure_schema_current(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema, set_schema_version
            create_schema(conn)
            set_schema_version(conn)
            conn.close()
            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from preflight import ensure_schema
                result = ensure_schema()
            self.assertEqual(result, "current")

    def test_get_recent_summaries(self):
        from preflight import get_recent_summaries
        from db import ensure_session, record_summary
        ensure_session(self.conn, "s1")
        record_summary(self.conn, "s1", title="Session one", agent_summary="Did work on auth")
        self.conn.commit()
        summaries = get_recent_summaries(self.conn)
        self.assertTrue(len(summaries) >= 1)
        self.assertIn("Did work on auth", "\n".join(summaries))

    def test_get_recent_summaries_empty(self):
        from preflight import get_recent_summaries
        summaries = get_recent_summaries(self.conn)
        self.assertEqual(summaries, [])

    def test_find_relevant_sessions(self):
        from preflight import find_relevant_sessions
        from db import ensure_session, record_message
        ensure_session(self.conn, "s1")
        record_message(self.conn, "s1", "assistant", "Modified dashboard.py and fixed the layout")
        self.conn.execute("UPDATE sessions SET title = 'Dashboard work' WHERE id = 's1'")
        self.conn.commit()
        results = find_relevant_sessions(self.conn, ["dashboard.py"], set())
        self.assertTrue(len(results) >= 1)
        self.assertIn("Dashboard work", "\n".join(results))

    def test_find_relevant_sessions_excludes(self):
        from preflight import find_relevant_sessions
        from db import ensure_session, record_message
        ensure_session(self.conn, "s1")
        record_message(self.conn, "s1", "assistant", "Modified dashboard.py")
        self.conn.execute("UPDATE sessions SET title = 'Dashboard work' WHERE id = 's1'")
        self.conn.commit()
        results = find_relevant_sessions(self.conn, ["dashboard.py"], {"s1"})
        self.assertEqual(results, [])

    def test_get_session_context_structure(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema, set_schema_version
            create_schema(conn)
            set_schema_version(conn)
            conn.close()
            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from preflight import get_session_context
                context = get_session_context()
            self.assertTrue(context.startswith("# Larvling Session Context"))

    def test_orphaned_loop_detection(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema, set_schema_version, ensure_session, create_loop
            create_schema(conn)
            set_schema_version(conn)
            ensure_session(conn, "orphan-sess")
            create_loop(conn, "orphan-sess", "abandoned task", max_iterations=3)
            conn.commit()
            conn.close()
            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from preflight import get_session_context
                context = get_session_context()
            self.assertIn("Orphaned Loops", context)
            self.assertIn("abandoned task", context)


# ---------------------------------------------------------------------------
# Dashboard Rendering Tests
# ---------------------------------------------------------------------------


class TestDashboardRendering(unittest.TestCase):
    """Test dashboard.py rendering functions."""

    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def test_render_message_user(self):
        from dashboard import render_message
        msg = {"role": "user", "content": "hello world", "timestamp": "2025-01-01 12:00:00", "metadata": None}
        html = render_message(msg)
        self.assertIn("msg-user", html)
        self.assertIn("You", html)
        self.assertIn("hello world", html)

    def test_render_message_agent(self):
        from dashboard import render_message
        msg = {"role": "assistant", "content": "I helped", "timestamp": "2025-01-01 12:01:00", "metadata": None}
        html = render_message(msg)
        self.assertIn("msg-agent", html)
        self.assertIn("Agent", html)

    def test_render_message_with_tools(self):
        from dashboard import render_message
        meta = json.dumps({"tool_calls": {"Read": 3, "Write": 1}})
        msg = {"role": "assistant", "content": "done", "timestamp": "2025-01-01 12:01:00", "metadata": meta}
        html = render_message(msg)
        self.assertIn("tool-badge", html)
        self.assertIn("Read", html)

    def test_render_message_system(self):
        from dashboard import render_message
        msg = {"role": "system", "content": "context loaded", "timestamp": "2025-01-01 12:00:00", "metadata": None}
        html = render_message(msg)
        self.assertIn("msg-system", html)

    def test_render_sidebar_item(self):
        from dashboard import render_sidebar_item
        session = {
            "session_id": "abcdef01-2345-6789-abcd-ef0123456789",
            "started": "2025-01-15 10:30:00",
            "ended": "2025-01-15 11:00:00",
            "msg_count": 12,
            "messages": [],
            "meta": {"duration_min": 30, "title": "Fixed the auth bug", "agent_summary": None},
        }
        html = render_sidebar_item(session, 0)
        self.assertIn("2025-01-15", html)
        self.assertIn("12 msgs", html)
        self.assertIn("Fixed the auth bug", html)
        self.assertIn("active", html)

    def test_render_page_replaces_placeholders(self):
        from dashboard import render_page
        html = render_page(
            "<div>sidebar</div>", "<div>details</div>", 42,
            loop_sidebar="<div>loops</div>",
            loop_details="<div>loop detail</div>",
            loop_banner="<div>banner</div>",
        )
        self.assertNotIn("{{SIDEBAR}}", html)
        self.assertNotIn("{{DETAILS}}", html)
        self.assertNotIn("{{REVISION}}", html)
        self.assertNotIn("{{LOOP_SIDEBAR}}", html)
        self.assertNotIn("{{LOOP_DETAILS}}", html)
        self.assertNotIn("{{LOOP_BANNER}}", html)
        self.assertIn("42", html)

    def test_get_revision_changes(self):
        from dashboard import get_revision
        from db import ensure_session, record_message
        rev1 = get_revision(self.conn)
        ensure_session(self.conn, "s1")
        record_message(self.conn, "s1", "user", "hello")
        self.conn.commit()
        rev2 = get_revision(self.conn)
        self.assertGreater(rev2, rev1)


# ---------------------------------------------------------------------------
# Loop CRUD Tests
# ---------------------------------------------------------------------------


class TestLoopCRUD(unittest.TestCase):
    """Test loop operations from db.py."""

    def setUp(self):
        self.conn = make_db()
        from db import ensure_session
        ensure_session(self.conn, "test-sess")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_create_loop(self):
        from db import create_loop
        lid = create_loop(self.conn, "test-sess", "build something", 3, "DONE")
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM loops WHERE id = ?", (lid,)).fetchone()
        self.assertEqual(row["prompt"], "build something")
        self.assertEqual(row["max_iterations"], 3)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["iteration"], 1)

    def test_create_loop_empty_prompt_rejected(self):
        from db import create_loop
        with self.assertRaises(ValueError):
            create_loop(self.conn, "test-sess", "")

    def test_create_loop_negative_max_rejected(self):
        from db import create_loop
        with self.assertRaises(ValueError):
            create_loop(self.conn, "test-sess", "task", max_iterations=-1)

    def test_get_active_loop(self):
        from db import create_loop, get_active_loop
        create_loop(self.conn, "test-sess", "task")
        self.conn.commit()
        loop = get_active_loop(self.conn, "test-sess")
        self.assertIsNotNone(loop)
        self.assertEqual(loop["status"], "active")

    def test_get_any_active_loop(self):
        from db import create_loop, get_any_active_loop
        create_loop(self.conn, "test-sess", "task")
        self.conn.commit()
        loop = get_any_active_loop(self.conn)
        self.assertIsNotNone(loop)

    def test_increment_loop(self):
        from db import create_loop, increment_loop
        lid = create_loop(self.conn, "test-sess", "task", 10)
        self.conn.commit()
        increment_loop(self.conn, lid)
        self.conn.commit()
        row = self.conn.execute("SELECT iteration FROM loops WHERE id = ?", (lid,)).fetchone()
        self.assertEqual(row["iteration"], 2)

    def test_end_loop(self):
        from db import create_loop, end_loop
        lid = create_loop(self.conn, "test-sess", "task", 10, "DONE")
        self.conn.commit()
        end_loop(self.conn, lid, "completed", "DONE")
        self.conn.commit()
        row = self.conn.execute("SELECT status, outcome FROM loops WHERE id = ?", (lid,)).fetchone()
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["outcome"], "DONE")

    def test_end_loop_idempotent(self):
        from db import create_loop, end_loop
        lid = create_loop(self.conn, "test-sess", "task", 10)
        self.conn.commit()
        end_loop(self.conn, lid, "completed", "first")
        self.conn.commit()
        end_loop(self.conn, lid, "cancelled", "second")
        self.conn.commit()
        row = self.conn.execute("SELECT status, outcome FROM loops WHERE id = ?", (lid,)).fetchone()
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["outcome"], "first")

    def test_increment_finished_loop_noop(self):
        from db import create_loop, end_loop, increment_loop
        lid = create_loop(self.conn, "test-sess", "task", 10)
        self.conn.commit()
        end_loop(self.conn, lid, "exhausted")
        self.conn.commit()
        increment_loop(self.conn, lid)
        self.conn.commit()
        row = self.conn.execute("SELECT iteration FROM loops WHERE id = ?", (lid,)).fetchone()
        self.assertEqual(row["iteration"], 1)


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    """Edge cases: concurrency, large content, unicode, SQL injection, schema versioning."""

    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def test_concurrent_sessions_no_interference(self):
        from db import ensure_session, record_message
        ensure_session(self.conn, "sess-A")
        ensure_session(self.conn, "sess-B")
        record_message(self.conn, "sess-A", "user", "message for A")
        record_message(self.conn, "sess-B", "user", "message for B")
        self.conn.commit()
        a_msgs = self.conn.execute("SELECT content FROM messages WHERE session_id = 'sess-A'").fetchall()
        b_msgs = self.conn.execute("SELECT content FROM messages WHERE session_id = 'sess-B'").fetchall()
        self.assertEqual(len(a_msgs), 1)
        self.assertEqual(len(b_msgs), 1)
        self.assertEqual(a_msgs[0]["content"], "message for A")
        self.assertEqual(b_msgs[0]["content"], "message for B")

    def test_long_content_stores_correctly(self):
        from db import ensure_session, record_message
        long_text = "x" * 15000
        ensure_session(self.conn, "sess-long")
        record_message(self.conn, "sess-long", "assistant", long_text)
        self.conn.commit()
        row = self.conn.execute("SELECT content FROM messages WHERE session_id = 'sess-long'").fetchone()
        self.assertEqual(len(row["content"]), 15000)

    def test_unicode_emoji_cjk_stores_correctly(self):
        from db import ensure_session, record_message
        unicode_text = "Hello \U0001f600 \u4f60\u597d \U0001f41b \u30e9\u30fc\u30d6\u30ea\u30f3\u30b0"
        ensure_session(self.conn, "sess-uni")
        record_message(self.conn, "sess-uni", "user", unicode_text)
        self.conn.commit()
        row = self.conn.execute("SELECT content FROM messages WHERE session_id = 'sess-uni'").fetchone()
        self.assertEqual(row["content"], unicode_text)

    def test_sql_special_chars_in_content(self):
        from db import ensure_session, record_message, record_summary
        tricky = "Robert'); DROP TABLE sessions;--"
        ensure_session(self.conn, "sess-sql")
        record_message(self.conn, "sess-sql", "user", tricky)
        record_summary(self.conn, "sess-sql", title="It's a 100% test_case")
        self.conn.commit()
        row = self.conn.execute("SELECT content FROM messages WHERE session_id = 'sess-sql'").fetchone()
        self.assertEqual(row["content"], tricky)
        tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
        self.assertEqual(tables, {"sessions", "messages", "facts", "loops"})

    def test_schema_version_roundtrip(self):
        from db import get_schema_version, set_schema_version, SCHEMA_VERSION
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.assertEqual(get_schema_version(conn), 0)
        set_schema_version(conn, SCHEMA_VERSION)
        self.assertEqual(get_schema_version(conn), SCHEMA_VERSION)
        conn.close()

    def test_parse_meta_handles_edge_cases(self):
        from db import parse_meta
        self.assertEqual(parse_meta(None), {})
        self.assertEqual(parse_meta(""), {})
        self.assertEqual(parse_meta("not json at all"), {})
        self.assertEqual(parse_meta('{"a": 1}'), {"a": 1})


# ---------------------------------------------------------------------------
# Loop Completion & Context Tests (hooks.py)
# ---------------------------------------------------------------------------


class TestLoopCompletion(unittest.TestCase):
    """Test _check_loop_completion and _build_loop_context from hooks.py."""

    def _make_loop_dict(self, **overrides):
        defaults = {
            "id": 1,
            "session_id": "test-sess",
            "prompt": "build something",
            "status": "active",
            "iteration": 1,
            "max_iterations": 5,
            "completion_promise": "DONE",
            "started_at": "2025-01-01 00:00:00",
            "ended_at": None,
            "outcome": None,
        }
        defaults.update(overrides)
        return defaults

    def test_check_completion_promise_found(self):
        from hooks import _check_loop_completion
        loop = self._make_loop_dict(completion_promise="TASK_DONE")
        result = _check_loop_completion(loop, "I finished the work <promise>TASK_DONE</promise>")
        self.assertEqual(result, ("completed", "TASK_DONE"))

    def test_check_completion_promise_case_insensitive(self):
        from hooks import _check_loop_completion
        loop = self._make_loop_dict(completion_promise="TASK_DONE")
        result = _check_loop_completion(loop, "<PROMISE>TASK_DONE</PROMISE> done")
        self.assertEqual(result, ("completed", "TASK_DONE"))

    def test_check_completion_promise_with_whitespace(self):
        from hooks import _check_loop_completion
        loop = self._make_loop_dict(completion_promise="TASK_DONE")
        result = _check_loop_completion(loop, "<promise>  TASK_DONE  </promise>")
        self.assertEqual(result, ("completed", "TASK_DONE"))

    def test_check_completion_no_promise(self):
        from hooks import _check_loop_completion
        loop = self._make_loop_dict(completion_promise="TASK_DONE")
        result = _check_loop_completion(loop, "Still working on it")
        self.assertIsNone(result)

    def test_check_completion_max_iterations_reached(self):
        from hooks import _check_loop_completion
        loop = self._make_loop_dict(iteration=5, max_iterations=5, completion_promise=None)
        result = _check_loop_completion(loop, "Some response")
        self.assertEqual(result[0], "exhausted")
        self.assertIn("max iterations", result[1])

    def test_check_completion_no_response_early(self):
        """On iteration 1, missing response should not exhaust."""
        from hooks import _check_loop_completion
        loop = self._make_loop_dict(iteration=1, completion_promise=None)
        result = _check_loop_completion(loop, None)
        self.assertIsNone(result)

    def test_check_completion_no_response_late(self):
        """On iteration > 1, missing response should exhaust."""
        from hooks import _check_loop_completion
        loop = self._make_loop_dict(iteration=3, completion_promise=None)
        result = _check_loop_completion(loop, None)
        self.assertEqual(result[0], "exhausted")

    def test_check_completion_promise_trumps_max_iter(self):
        """Promise found on the last iteration should be 'completed', not 'exhausted'."""
        from hooks import _check_loop_completion
        loop = self._make_loop_dict(iteration=5, max_iterations=5, completion_promise="DONE")
        result = _check_loop_completion(loop, "Finished <promise>DONE</promise>")
        self.assertEqual(result[0], "completed")

    def test_check_completion_unlimited(self):
        """max_iterations=0 means unlimited — should not exhaust."""
        from hooks import _check_loop_completion
        loop = self._make_loop_dict(iteration=100, max_iterations=0, completion_promise=None)
        result = _check_loop_completion(loop, "Still going")
        self.assertIsNone(result)

    def test_build_loop_context_finds_facts(self):
        from hooks import _build_loop_context
        conn = make_db()
        from db import ensure_session
        ensure_session(conn, "test-sess")
        conn.execute(
            "INSERT INTO facts (id, claim, domain, tags, source) "
            "VALUES ('f1', 'Python uses indentation for blocks', 'technical', 'python,syntax', 'test')"
        )
        conn.commit()
        loop = self._make_loop_dict(prompt="Fix the Python indentation error")
        context = _build_loop_context(conn, loop, "test-sess")
        self.assertIn("Python uses indentation", context)
        conn.close()

    def test_build_loop_context_finds_progress(self):
        from hooks import _build_loop_context
        conn = make_db()
        from db import ensure_session, record_message
        ensure_session(conn, "test-sess")
        record_message(conn, "test-sess", "assistant", "Fixed the login bug and added tests")
        conn.commit()
        loop = self._make_loop_dict(prompt="Fix bugs in the login system", started_at="2000-01-01 00:00:00")
        context = _build_loop_context(conn, loop, "test-sess")
        self.assertIn("Fixed the login bug", context)
        conn.close()

    def test_build_loop_context_empty_when_no_data(self):
        from hooks import _build_loop_context
        conn = make_db()
        from db import ensure_session
        ensure_session(conn, "test-sess")
        conn.commit()
        loop = self._make_loop_dict(prompt="something obscure xyzzyx")
        context = _build_loop_context(conn, loop, "test-sess")
        self.assertEqual(context, "")
        conn.close()

    def test_build_loop_context_always_includes_loop_facts(self):
        """Facts with source='loop-{id}' are always surfaced even if keywords don't match."""
        from hooks import _build_loop_context
        conn = make_db()
        from db import ensure_session
        ensure_session(conn, "test-sess")
        conn.execute(
            "INSERT INTO facts (id, claim, domain, tags, source) "
            "VALUES ('L1-progress', 'DONE: step1 | REMAINING: step2', 'loop-progress', 'loop,progress', 'loop-1')"
        )
        conn.execute(
            "INSERT INTO facts (id, claim, domain, tags, source) "
            "VALUES ('L1-I1-a', 'Discovered widget API is unstable', 'loop-discovery', 'discovery', 'loop-1')"
        )
        conn.commit()
        # Use a prompt with words that DON'T match any fact claims
        loop = self._make_loop_dict(id=1, prompt="Completely unrelated zebra dancing moonlight")
        context = _build_loop_context(conn, loop, "test-sess")
        self.assertIn("Loop facts:", context)
        self.assertIn("L1-progress", context)
        self.assertIn("L1-I1-a", context)
        self.assertIn("widget API is unstable", context)
        conn.close()

    def test_build_loop_context_deduplicates_facts(self):
        """Facts found by both source and keyword should only appear once."""
        from hooks import _build_loop_context
        conn = make_db()
        from db import ensure_session
        ensure_session(conn, "test-sess")
        conn.execute(
            "INSERT INTO facts (id, claim, domain, tags, source) "
            "VALUES ('L1-I1-a', 'Python indentation matters for blocks', 'loop-discovery', 'python', 'loop-1')"
        )
        conn.commit()
        # This prompt has 'Python' which would match the fact by keyword too
        loop = self._make_loop_dict(id=1, prompt="Fix Python indentation errors")
        context = _build_loop_context(conn, loop, "test-sess")
        # Should appear in loop facts section, not duplicated in relevant facts
        self.assertIn("Loop facts:", context)
        self.assertEqual(context.count("L1-I1-a"), 1)
        conn.close()


# ---------------------------------------------------------------------------
# Export Tests
# ---------------------------------------------------------------------------


class TestExport(unittest.TestCase):
    """Test export.py rendering functions."""

    def test_export_session_basic(self):
        from export import export_session
        conn = make_db()
        from db import ensure_session, record_message, record_summary
        ensure_session(conn, "exp-sess")
        record_message(conn, "exp-sess", "user", "How do I fix this?")
        record_message(conn, "exp-sess", "assistant", "Here's the fix...")
        record_summary(conn, "exp-sess", title="Fixing a bug")
        conn.commit()
        md = export_session("exp-sess", conn)
        self.assertIn("# Session exp-sess", md)
        self.assertIn("How do I fix this?", md)
        self.assertIn("Here's the fix...", md)
        self.assertIn("**Title:** Fixing a bug", md)
        conn.close()

    def test_export_session_with_tools(self):
        from export import export_session
        conn = make_db()
        from db import ensure_session, record_message
        ensure_session(conn, "exp-sess")
        record_message(conn, "exp-sess", "user", "Read the file")
        meta = {"tool_calls": {"Read": 2}}
        record_message(conn, "exp-sess", "assistant", "Contents here", meta)
        conn.commit()
        md = export_session("exp-sess", conn)
        self.assertIn("Read (2x)", md)
        conn.close()

    def test_export_session_no_messages(self):
        from export import export_session
        conn = make_db()
        from db import ensure_session
        ensure_session(conn, "exp-empty")
        conn.commit()
        md = export_session("exp-empty", conn)
        self.assertIsNone(md)
        conn.close()

    def test_export_session_not_found(self):
        from export import export_session
        conn = make_db()
        md = export_session("nonexistent", conn)
        self.assertIsNone(md)
        conn.close()


# ---------------------------------------------------------------------------
# Summarize Tests
# ---------------------------------------------------------------------------


class TestSummarize(unittest.TestCase):
    """Test summarize.py pair extraction and summary storage."""

    def test_get_pairs_basic(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema, ensure_session, record_message
            create_schema(conn)
            ensure_session(conn, "pair-sess")
            record_message(conn, "pair-sess", "user", "What is 2+2?")
            record_message(conn, "pair-sess", "assistant", "4")
            record_message(conn, "pair-sess", "user", "And 3+3?")
            record_message(conn, "pair-sess", "assistant", "6")
            conn.commit()
            conn.close()

            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from summarize import get_pairs
                pairs = get_pairs("pair-sess")
            self.assertEqual(len(pairs), 2)
            self.assertEqual(pairs[0]["user"], "What is 2+2?")
            self.assertEqual(pairs[0]["agent"], "4")
            self.assertEqual(pairs[1]["user"], "And 3+3?")
            self.assertEqual(pairs[1]["agent"], "6")

    def test_get_pairs_not_found(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema
            create_schema(conn)
            conn.close()

            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from summarize import get_pairs
                pairs = get_pairs("nonexistent")
            self.assertIsNone(pairs)

    def test_store_and_get_summary(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema, ensure_session, record_message
            create_schema(conn)
            ensure_session(conn, "sum-sess")
            record_message(conn, "sum-sess", "user", "hello")
            conn.commit()
            conn.close()

            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from summarize import store_summary, get_existing_summary
                store_summary("sum-sess", "This was a productive session")
                result = get_existing_summary("sum-sess")
            self.assertEqual(result, "This was a productive session")


# ---------------------------------------------------------------------------
# Dashboard Loop Rendering Tests
# ---------------------------------------------------------------------------


class TestDashboardLoops(unittest.TestCase):
    """Test loop-specific dashboard rendering functions."""

    def _make_loop_row(self, **overrides):
        defaults = {
            "id": 1,
            "session_id": "test-sess",
            "prompt": "Build a feature",
            "status": "active",
            "iteration": 3,
            "max_iterations": 10,
            "completion_promise": "DONE",
            "started_at": "2025-06-15 14:30:00",
            "ended_at": None,
            "outcome": None,
        }
        defaults.update(overrides)
        return defaults

    def test_render_loop_sidebar_item(self):
        from dashboard import render_loop_sidebar_item
        loop = self._make_loop_row()
        html = render_loop_sidebar_item(loop, 0)
        self.assertIn("loop-entry", html)
        self.assertIn("loop-status-active", html)
        self.assertIn("Build a feature", html)
        self.assertIn("iter 3/10", html)
        self.assertIn("2025-06-15", html)

    def test_render_loop_detail_active(self):
        from dashboard import render_loop_detail
        loop = self._make_loop_row()
        html = render_loop_detail(loop)
        self.assertIn("loop-detail", html)
        self.assertIn("loop-progress-active", html)
        self.assertIn("Build a feature", html)
        self.assertIn("DONE", html)

    def test_render_loop_detail_completed(self):
        from dashboard import render_loop_detail
        loop = self._make_loop_row(
            status="completed",
            ended_at="2025-06-15 15:00:00",
            outcome="All done"
        )
        html = render_loop_detail(loop)
        self.assertIn("loop-status-completed", html)
        self.assertIn("All done", html)
        self.assertNotIn("loop-progress-active", html)

    def test_render_loop_banner_active(self):
        from dashboard import render_loop_banner
        loops = [self._make_loop_row()]
        html = render_loop_banner(loops)
        self.assertIn("loop-banner", html)
        self.assertIn("iter 3/10", html)

    def test_render_loop_banner_no_active(self):
        from dashboard import render_loop_banner
        loops = [self._make_loop_row(status="completed")]
        html = render_loop_banner(loops)
        self.assertEqual(html, "")

    def test_render_loop_detail_unlimited(self):
        from dashboard import render_loop_detail
        loop = self._make_loop_row(max_iterations=0, iteration=7)
        html = render_loop_detail(loop)
        self.assertIn("iter 7", html)
        self.assertNotIn("loop-progress-wrap", html)


# ---------------------------------------------------------------------------
# Preflight Update Check Tests
# ---------------------------------------------------------------------------


class TestPreflightUpdateCheck(unittest.TestCase):
    """Test check_update with mocked network."""

    def test_check_update_no_plugin_json(self):
        from preflight import check_update
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/nonexistent"}):
            result = check_update()
        self.assertIsNone(result)

    def test_check_update_up_to_date(self):
        from preflight import check_update
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = os.path.join(tmpdir, ".claude-plugin")
            os.makedirs(plugin_dir)
            with open(os.path.join(plugin_dir, "plugin.json"), "w") as f:
                json.dump({"version": "1.0.0"}, f)
            with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": tmpdir}):
                resp_data = json.dumps({"tag_name": "v1.0.0"}).encode()
                mock_resp = mock.MagicMock()
                mock_resp.read.return_value = resp_data
                mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = mock.MagicMock(return_value=False)
                with mock.patch("urllib.request.urlopen", return_value=mock_resp):
                    result = check_update()
        self.assertIsNone(result)

    def test_check_update_newer_available(self):
        from preflight import check_update
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = os.path.join(tmpdir, ".claude-plugin")
            os.makedirs(plugin_dir)
            with open(os.path.join(plugin_dir, "plugin.json"), "w") as f:
                json.dump({"version": "0.1.0"}, f)
            with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": tmpdir}):
                resp_data = json.dumps({"tag_name": "v1.0.0"}).encode()
                mock_resp = mock.MagicMock()
                mock_resp.read.return_value = resp_data
                mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = mock.MagicMock(return_value=False)
                with mock.patch("urllib.request.urlopen", return_value=mock_resp):
                    result = check_update()
        self.assertIsNotNone(result)
        self.assertIn("update available", result)

    def test_check_update_network_failure(self):
        from preflight import check_update
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = os.path.join(tmpdir, ".claude-plugin")
            os.makedirs(plugin_dir)
            with open(os.path.join(plugin_dir, "plugin.json"), "w") as f:
                json.dump({"version": "0.1.0"}, f)
            with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": tmpdir}):
                with mock.patch("urllib.request.urlopen", side_effect=Exception("timeout")):
                    result = check_update()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Handle Stop Integration Tests
# ---------------------------------------------------------------------------


class TestHandleStopIntegration(unittest.TestCase):
    """Test handle_stop with active loops and transcript parsing."""

    def _setup_db(self, tmpdir):
        test_db = os.path.join(tmpdir, ".claude", "larvling.db")
        os.makedirs(os.path.dirname(test_db))
        conn = sqlite3.connect(test_db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        from db import create_schema, ensure_session
        create_schema(conn)
        ensure_session(conn, "test-sess")
        conn.commit()
        conn.close()
        return test_db

    def test_handle_stop_no_loop_logs_response(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = self._setup_db(tmpdir)
            transcript = os.path.join(tmpdir, "transcript.jsonl")
            with open(transcript, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "do work"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "I did it"}]}}) + "\n")

            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from hooks import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            msg = conn.execute("SELECT content FROM messages WHERE role = 'assistant'").fetchone()
            self.assertIsNotNone(msg)
            self.assertEqual(msg["content"], "I did it")
            conn.close()

    def test_handle_stop_active_loop_blocks_exit(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = self._setup_db(tmpdir)
            # Create active loop
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_loop
            create_loop(conn, "test-sess", "Build feature X", 5, "FEATURE_DONE")
            conn.commit()
            conn.close()

            transcript = os.path.join(tmpdir, "transcript.jsonl")
            with open(transcript, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "start"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Working on it"}]}}) + "\n")

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from hooks import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})

            output = captured.getvalue()
            block = json.loads(output)
            self.assertEqual(block["decision"], "block")
            self.assertEqual(block["reason"], "Build feature X")
            self.assertIn("Loop iteration", block["systemMessage"])

            # Verify iteration was incremented
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT iteration FROM loops WHERE status = 'active'").fetchone()
            self.assertEqual(loop["iteration"], 2)
            conn.close()

    def test_handle_stop_loop_completes_on_promise(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = self._setup_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_loop
            create_loop(conn, "test-sess", "Build it", 5, "ALL_DONE")
            conn.commit()
            conn.close()

            transcript = os.path.join(tmpdir, "transcript.jsonl")
            with open(transcript, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "go"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Finished! <promise>ALL_DONE</promise>"}]}}) + "\n")

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from hooks import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})

            # Should NOT block exit — no output expected
            output = captured.getvalue().strip()
            self.assertEqual(output, "")

            # Verify loop is completed
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT status, outcome FROM loops").fetchone()
            self.assertEqual(loop["status"], "completed")
            self.assertEqual(loop["outcome"], "ALL_DONE")
            conn.close()

    def test_handle_stop_system_message_includes_fact_management(self):
        """Verify the block system message includes fact management instructions."""
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = self._setup_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_loop
            create_loop(conn, "test-sess", "Evolve the framework", 10, "EVOLVED")
            conn.commit()
            conn.close()

            transcript = os.path.join(tmpdir, "transcript.jsonl")
            with open(transcript, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "go"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Started work"}]}}) + "\n")

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from hooks import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})

            block = json.loads(captured.getvalue())
            sys_msg = block["systemMessage"]
            # Should include progress tracker instructions
            self.assertIn("progress tracker", sys_msg.lower())
            self.assertIn("INSERT OR REPLACE", sys_msg)
            # Should include fact management CRUD instructions
            self.assertIn("Insert", sys_msg)
            self.assertIn("Update", sys_msg)
            self.assertIn("Delete", sys_msg)
            # Should include ID convention
            self.assertIn("L", sys_msg)
            self.assertIn("loop-discovery", sys_msg)

    def test_handle_stop_duplicate_response_not_logged(self):
        """If the same response was already logged, don't log it again."""
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = self._setup_db(tmpdir)
            # Pre-log a response
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES ('test-sess', 'assistant', 'Same response')"
            )
            conn.commit()
            conn.close()

            transcript = os.path.join(tmpdir, "transcript.jsonl")
            with open(transcript, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "do it"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Same response"}]}}) + "\n")

            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from hooks import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            count = conn.execute("SELECT COUNT(*) FROM messages WHERE role = 'assistant'").fetchone()[0]
            self.assertEqual(count, 1)  # Should still be just 1, not duplicated
            conn.close()


# ---------------------------------------------------------------------------
# Hooks Main Dispatch Tests
# ---------------------------------------------------------------------------


class TestHooksDispatch(unittest.TestCase):
    """Test the main() dispatch function in hooks.py."""

    def test_dispatch_user_prompt_submit(self):
        from hooks import main as hooks_main
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema
            create_schema(conn)
            conn.close()

            data = json.dumps({
                "hook_event_name": "UserPromptSubmit",
                "session_id": "dispatch-test",
                "prompt": "Hello dispatch",
            })
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(data.encode()))):
                hooks_main()

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            msg = conn.execute("SELECT content FROM messages").fetchone()
            self.assertIsNotNone(msg)
            self.assertEqual(msg["content"], "Hello dispatch")
            conn.close()

    def test_dispatch_session_end(self):
        from hooks import main as hooks_main
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema, ensure_session
            create_schema(conn)
            ensure_session(conn, "dispatch-end")
            conn.commit()
            conn.close()

            data = json.dumps({
                "hook_event_name": "SessionEnd",
                "session_id": "dispatch-end",
            })
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(data.encode()))):
                hooks_main()

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            sess = conn.execute("SELECT ended_at FROM sessions WHERE id = 'dispatch-end'").fetchone()
            self.assertIsNotNone(sess["ended_at"])
            conn.close()

    def test_dispatch_unknown_event_noop(self):
        """Unknown events should not raise."""
        from hooks import main as hooks_main
        data = json.dumps({"hook_event_name": "SomeUnknownEvent", "session_id": "x"})
        with mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(data.encode()))):
            hooks_main()  # Should not raise

    def test_dispatch_empty_stdin_noop(self):
        """Empty stdin should not raise."""
        from hooks import main as hooks_main
        with mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(b""))):
            hooks_main()  # Should not raise

    def test_dispatch_invalid_json_noop(self):
        """Invalid JSON should not raise (logged to error file)."""
        from hooks import main as hooks_main
        with mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(b"not json{{{"))):
            hooks_main()  # Should not raise


if __name__ == "__main__":
    unittest.main()
