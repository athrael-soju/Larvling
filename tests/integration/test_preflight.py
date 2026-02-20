"""Preflight tests — context generation, fact review, update checks."""

import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from conftest import make_db


class TestPreflightContext(unittest.TestCase):

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


class TestPreflightFactReview(unittest.TestCase):
    """Test missed fact review detection in preflight context."""

    def test_missed_review_detected(self):
        """Session with 6+ exchanges and no fact review triggers reminder."""
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema, set_schema_version, ensure_session, record_message
            create_schema(conn)
            set_schema_version(conn)
            ensure_session(conn, "review-sess")
            for i in range(7):
                record_message(conn, "review-sess", "user", f"message {i}")
                record_message(conn, "review-sess", "assistant", f"reply {i}")
            conn.execute("UPDATE sessions SET title = 'Productive session' WHERE id = 'review-sess'")
            conn.commit()
            conn.close()

            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from preflight import get_session_context
                context = get_session_context()
            self.assertIn("Missed Fact Review", context)
            self.assertIn("review-s", context)

    def test_no_missed_review_when_facts_exist(self):
        """Session with fact review should NOT trigger reminder."""
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema, set_schema_version, ensure_session, record_message
            create_schema(conn)
            set_schema_version(conn)
            ensure_session(conn, "reviewed-s")
            for i in range(7):
                record_message(conn, "reviewed-s", "user", f"message {i}")
            conn.execute(
                "INSERT INTO facts (id, claim, source) VALUES ('M-001', 'some fact', 'session-reviewed')"
            )
            conn.commit()
            conn.close()

            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from preflight import get_session_context
                context = get_session_context()
            self.assertNotIn("Missed Fact Review", context)

    def test_no_missed_review_short_session(self):
        """Session with fewer than 6 exchanges should NOT trigger reminder."""
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, ".claude", "larvling.db")
            os.makedirs(os.path.dirname(test_db))
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_schema, set_schema_version, ensure_session, record_message
            create_schema(conn)
            set_schema_version(conn)
            ensure_session(conn, "short-sess")
            for i in range(3):
                record_message(conn, "short-sess", "user", f"message {i}")
            conn.commit()
            conn.close()

            with mock.patch.object(db_mod, "DB_PATH", test_db):
                from preflight import get_session_context
                context = get_session_context()
            self.assertNotIn("Missed Fact Review", context)


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
