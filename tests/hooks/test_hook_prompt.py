"""hook_prompt tests — handle_user_prompt, inject_relevant_facts, main dispatch."""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from conftest import make_db, setup_test_db


class TestHookPrompt(unittest.TestCase):

    def test_handle_user_prompt_records(self):
        import db
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            with mock.patch.object(db, "DB_PATH", test_db):
                from hook_prompt import handle_user_prompt
                handle_user_prompt({
                    "session_id": "test-sess",
                    "prompt": "Build a feature",
                    "cwd": "/tmp",
                    "permission_mode": "default",
                })
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            msg = conn.execute("SELECT * FROM messages WHERE session_id = 'test-sess'").fetchone()
            self.assertEqual(msg["role"], "user")
            self.assertEqual(msg["content"], "Build a feature")
            sess = conn.execute("SELECT title FROM sessions WHERE id = 'test-sess'").fetchone()
            self.assertEqual(sess["title"], "Build a feature")
            conn.close()

    def test_handle_user_prompt_skipped_for_agent(self):
        import db
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            with mock.patch.object(db, "DB_PATH", test_db), \
                 mock.patch.dict(os.environ, {"LARVLING_AGENT": "1"}):
                from hook_prompt import handle_user_prompt
                handle_user_prompt({
                    "session_id": "test-sess",
                    "prompt": "Agent prompt",
                    "cwd": "/tmp",
                })
            conn = sqlite3.connect(test_db)
            count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()

    def test_handle_user_prompt_main_dispatch(self):
        from hook_prompt import main as prompt_main
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            data = json.dumps({"session_id": "dispatch-test", "prompt": "Hello dispatch"})
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(data.encode()))):
                prompt_main()
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            msg = conn.execute("SELECT content FROM messages").fetchone()
            self.assertEqual(msg["content"], "Hello dispatch")
            conn.close()


class TestFactRetrieval(unittest.TestCase):

    def test_matching_facts_printed(self):
        conn = make_db()
        conn.execute(
            "INSERT INTO facts (id, claim, domain, tags) "
            "VALUES ('M-001', 'Python uses indentation for blocks', 'technical', 'python,syntax')"
        )
        conn.commit()
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            from hook_prompt import inject_relevant_facts
            inject_relevant_facts(conn, "Fix the Python indentation error")
        output = captured.getvalue()
        self.assertIn("Relevant Facts", output)
        self.assertIn("M-001", output)
        self.assertIn("Python uses indentation", output)
        conn.close()

    def test_no_matching_facts(self):
        conn = make_db()
        conn.execute(
            "INSERT INTO facts (id, claim, domain) "
            "VALUES ('M-001', 'Database uses WAL mode', 'technical')"
        )
        conn.commit()
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            from hook_prompt import inject_relevant_facts
            inject_relevant_facts(conn, "Fix the xyzzyx bug")
        self.assertEqual(captured.getvalue(), "")
        conn.close()

    def test_empty_prompt(self):
        conn = make_db()
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            from hook_prompt import inject_relevant_facts
            inject_relevant_facts(conn, "hi")
        self.assertEqual(captured.getvalue(), "")
        conn.close()
