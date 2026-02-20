"""hook_end tests — handle_session_end, main dispatch."""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from conftest import setup_test_db


class TestHookEnd(unittest.TestCase):

    def test_handle_session_end_finalizes(self):
        import db
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session, record_message
            ensure_session(conn, "test-sess")
            record_message(conn, "test-sess", "user", "hello")
            record_message(conn, "test-sess", "assistant", "hi")
            conn.commit()
            conn.close()

            with mock.patch.object(db, "DB_PATH", test_db):
                from hook_end import handle_session_end
                handle_session_end({"session_id": "test-sess"})

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            sess = conn.execute("SELECT * FROM sessions WHERE id = 'test-sess'").fetchone()
            self.assertIsNotNone(sess["ended_at"])
            self.assertEqual(sess["exchange_count"], 1)
            conn.close()

    def test_handle_session_end_skipped_for_agent(self):
        import db
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session
            ensure_session(conn, "test-sess")
            conn.commit()
            conn.close()

            with mock.patch.object(db, "DB_PATH", test_db), \
                 mock.patch.dict(os.environ, {"LARVLING_AGENT": "1"}):
                from hook_end import handle_session_end
                handle_session_end({"session_id": "test-sess"})

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            sess = conn.execute("SELECT ended_at FROM sessions WHERE id = 'test-sess'").fetchone()
            self.assertIsNone(sess["ended_at"])
            conn.close()

    def test_handle_session_end_main_dispatch(self):
        from hook_end import main as end_main
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session
            ensure_session(conn, "dispatch-end")
            conn.commit()
            conn.close()

            data = json.dumps({"session_id": "dispatch-end"})
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(data.encode()))):
                end_main()

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            sess = conn.execute("SELECT ended_at FROM sessions WHERE id = 'dispatch-end'").fetchone()
            self.assertIsNotNone(sess["ended_at"])
            conn.close()
