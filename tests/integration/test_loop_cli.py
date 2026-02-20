"""loop.py CLI tests — cmd_start, cmd_cancel, cmd_status, main dispatch."""

import io
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from conftest import make_db, setup_test_db


class TestLoopStart(unittest.TestCase):

    def test_start_creates_loop(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            # Seed a session so start can find it
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session
            ensure_session(conn, "test-sess")
            conn.commit()
            conn.close()

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_start
                cmd_start(["Build", "the", "feature"])

            output = captured.getvalue()
            self.assertIn("Loop Started", output)
            self.assertIn("Build the feature", output)

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT * FROM loops WHERE status = 'active'").fetchone()
            self.assertIsNotNone(loop)
            self.assertEqual(loop["prompt"], "Build the feature")
            self.assertEqual(loop["max_iterations"], 0)
            self.assertIsNone(loop["completion_promise"])
            conn.close()

    def test_start_with_max_iterations(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session
            ensure_session(conn, "test-sess")
            conn.commit()
            conn.close()

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_start
                cmd_start(["Do", "work", "--max-iterations", "10"])

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT * FROM loops WHERE status = 'active'").fetchone()
            self.assertEqual(loop["max_iterations"], 10)
            self.assertEqual(loop["prompt"], "Do work")
            self.assertIn("max 10", captured.getvalue())
            conn.close()

    def test_start_with_completion_promise(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session
            ensure_session(conn, "test-sess")
            conn.commit()
            conn.close()

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_start
                cmd_start(["Build", "it", "--completion-promise", "ALL_DONE"])

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT * FROM loops WHERE status = 'active'").fetchone()
            self.assertEqual(loop["completion_promise"], "ALL_DONE")
            self.assertIn("ALL_DONE", captured.getvalue())
            conn.close()

    def test_start_with_all_options(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session
            ensure_session(conn, "test-sess")
            conn.commit()
            conn.close()

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_start
                cmd_start(["Refactor", "all", "--max-iterations", "5",
                           "--completion-promise", "REFACTORED"])

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT * FROM loops WHERE status = 'active'").fetchone()
            self.assertEqual(loop["prompt"], "Refactor all")
            self.assertEqual(loop["max_iterations"], 5)
            self.assertEqual(loop["completion_promise"], "REFACTORED")
            conn.close()

    def test_start_no_prompt_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            from loop import cmd_start
            cmd_start([])
        self.assertEqual(ctx.exception.code, 1)

    def test_start_negative_max_iterations_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            from loop import cmd_start
            cmd_start(["Do", "work", "--max-iterations", "-1"])
        self.assertEqual(ctx.exception.code, 1)

    def test_start_non_numeric_max_iterations_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            from loop import cmd_start
            cmd_start(["Do", "work", "--max-iterations", "abc"])
        self.assertEqual(ctx.exception.code, 1)

    def test_start_rejects_existing_active_loop(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session, create_loop
            ensure_session(conn, "test-sess")
            create_loop(conn, "test-sess", "Existing loop", 5, None)
            conn.commit()
            conn.close()

            with mock.patch.object(db_mod, "DB_PATH", test_db):
                with self.assertRaises(SystemExit) as ctx:
                    from loop import cmd_start
                    cmd_start(["Another", "loop"])
                self.assertEqual(ctx.exception.code, 1)

    def test_start_uses_session_id_env_var(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session
            ensure_session(conn, "env-sess-id")
            ensure_session(conn, "other-sess")
            conn.commit()
            conn.close()

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch.dict(os.environ, {"CLAUDE_SESSION_ID": "env-sess-id"}), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_start
                cmd_start(["Test", "env"])

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT session_id FROM loops WHERE status = 'active'").fetchone()
            self.assertEqual(loop["session_id"], "env-sess-id")
            conn.close()

    def test_start_no_session_exits(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch.dict(os.environ, {}, clear=True):
                # Ensure CLAUDE_SESSION_ID is not set
                os.environ.pop("CLAUDE_SESSION_ID", None)
                with self.assertRaises(SystemExit) as ctx:
                    from loop import cmd_start
                    cmd_start(["Test", "prompt"])
                self.assertEqual(ctx.exception.code, 1)


class TestLoopCancel(unittest.TestCase):

    def test_cancel_active_loop(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session, create_loop
            ensure_session(conn, "test-sess")
            create_loop(conn, "test-sess", "Build feature", 5, None)
            # Advance a few iterations
            conn.execute("UPDATE loops SET iteration = 3 WHERE status = 'active'")
            conn.commit()
            conn.close()

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_cancel
                cmd_cancel([])

            output = captured.getvalue()
            self.assertIn("cancelled", output.lower())
            self.assertIn("3", output)  # completed iterations count

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT status FROM loops").fetchone()
            self.assertEqual(loop["status"], "cancelled")
            conn.close()

    def test_cancel_no_active_loop(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_cancel
                cmd_cancel([])
            self.assertIn("No active loop", captured.getvalue())

    def test_cancel_race_condition_already_ended(self):
        """Simulate a loop that was ended between get_any_active_loop and end_loop."""
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session, create_loop
            ensure_session(conn, "test-sess")
            loop_id = create_loop(conn, "test-sess", "Build feature", 5, None)
            conn.commit()
            conn.close()

            # Now end the loop before cancel runs (simulate race)
            conn = sqlite3.connect(test_db)
            conn.execute(
                "UPDATE loops SET status = 'completed', ended_at = datetime('now') WHERE id = ?",
                (loop_id,),
            )
            conn.commit()
            conn.close()

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_cancel
                cmd_cancel([])

            # Should report no active loop since the loop is already finished
            self.assertIn("No active loop", captured.getvalue())


class TestLoopStatus(unittest.TestCase):

    def test_status_active_loop(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session, create_loop
            ensure_session(conn, "test-sess")
            create_loop(conn, "test-sess", "Build feature X", 10, "FEATURE_X_DONE")
            conn.execute("UPDATE loops SET iteration = 4 WHERE status = 'active'")
            conn.commit()
            conn.close()

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_status
                cmd_status([])

            output = captured.getvalue()
            self.assertIn("Active Loop", output)
            self.assertIn("4/10", output)
            self.assertIn("Build feature X", output)
            self.assertIn("FEATURE_X_DONE", output)

    def test_status_unlimited_loop(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import ensure_session, create_loop
            ensure_session(conn, "test-sess")
            create_loop(conn, "test-sess", "Explore ideas", 0, None)
            conn.execute("UPDATE loops SET iteration = 7 WHERE status = 'active'")
            conn.commit()
            conn.close()

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_status
                cmd_status([])

            output = captured.getvalue()
            self.assertIn("Active Loop", output)
            # Should show "7" without "/0"
            self.assertIn("7", output)
            self.assertNotIn("/0", output)

    def test_status_no_active_loop(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from loop import cmd_status
                cmd_status([])
            self.assertIn("No active loop", captured.getvalue())


class TestLoopMainDispatch(unittest.TestCase):

    def test_main_unknown_subcommand_exits(self):
        with mock.patch("sys.argv", ["loop.py", "unknown"]):
            with self.assertRaises(SystemExit) as ctx:
                from loop import main
                main()
            self.assertEqual(ctx.exception.code, 1)

    def test_main_no_args_exits(self):
        with mock.patch("sys.argv", ["loop.py"]):
            with self.assertRaises(SystemExit) as ctx:
                from loop import main
                main()
            self.assertEqual(ctx.exception.code, 1)

    def test_main_dispatches_status(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = setup_test_db(tmpdir)
            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.argv", ["loop.py", "status"]), \
                 mock.patch("sys.stdout", captured):
                from loop import main
                main()
            self.assertIn("No active loop", captured.getvalue())
