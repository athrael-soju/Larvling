"""Export and summarize tests — markdown export, pair extraction, summary storage."""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from conftest import make_db


class TestExport(unittest.TestCase):

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


class TestSummarize(unittest.TestCase):

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
