"""Database tests — CRUD operations, loop management, and edge cases."""

import io
import json
import sqlite3
import unittest
from unittest import mock

from conftest import make_db


class TestDatabaseCRUD(unittest.TestCase):

    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def test_create_schema_idempotent(self):
        from db import create_schema
        create_schema(self.conn)
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
        self.assertEqual(row["title"], "Test")
        self.assertEqual(row["agent_summary"], "A summary")

    def test_get_summary_missing(self):
        from db import get_summary
        self.assertIsNone(get_summary(self.conn, "nonexistent"))

    def test_resolve_session_full_id(self):
        from db import ensure_session, resolve_session
        full_id = "abcdef01-2345-6789-abcd-ef0123456789"
        ensure_session(self.conn, full_id)
        self.conn.commit()
        self.assertEqual(resolve_session(self.conn, full_id), full_id)

    def test_resolve_session_short_id(self):
        from db import ensure_session, resolve_session
        full_id = "abcdef01-2345-6789-abcd-ef0123456789"
        ensure_session(self.conn, full_id)
        self.conn.commit()
        self.assertEqual(resolve_session(self.conn, "abcdef01"), full_id)

    def test_resolve_session_no_match(self):
        from db import resolve_session
        self.assertIsNone(resolve_session(self.conn, "zzzzz"))

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


class TestLoopCRUD(unittest.TestCase):

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
        self.assertIsNotNone(get_any_active_loop(self.conn))

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


class TestEdgeCases(unittest.TestCase):

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
