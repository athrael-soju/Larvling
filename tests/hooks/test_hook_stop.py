"""hook_stop tests — _check_loop_completion, _build_loop_context, handle_stop integration."""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from conftest import make_db, setup_test_db


class TestLoopCompletion(unittest.TestCase):

    def _make_loop_dict(self, **overrides):
        defaults = {
            "id": 1, "session_id": "test-sess", "prompt": "build something",
            "status": "active", "iteration": 1, "max_iterations": 5,
            "completion_promise": "DONE", "started_at": "2025-01-01 00:00:00",
            "ended_at": None, "outcome": None,
        }
        defaults.update(overrides)
        return defaults

    def test_check_completion_promise_found(self):
        from hook_stop import _check_loop_completion
        loop = self._make_loop_dict(completion_promise="TASK_DONE")
        result = _check_loop_completion(loop, "I finished <promise>TASK_DONE</promise>")
        self.assertEqual(result, ("completed", "TASK_DONE"))

    def test_check_completion_promise_case_insensitive(self):
        from hook_stop import _check_loop_completion
        loop = self._make_loop_dict(completion_promise="TASK_DONE")
        result = _check_loop_completion(loop, "<PROMISE>TASK_DONE</PROMISE> done")
        self.assertEqual(result, ("completed", "TASK_DONE"))

    def test_check_completion_promise_with_whitespace(self):
        from hook_stop import _check_loop_completion
        loop = self._make_loop_dict(completion_promise="TASK_DONE")
        result = _check_loop_completion(loop, "<promise>  TASK_DONE  </promise>")
        self.assertEqual(result, ("completed", "TASK_DONE"))

    def test_check_completion_no_promise(self):
        from hook_stop import _check_loop_completion
        loop = self._make_loop_dict(completion_promise="TASK_DONE")
        self.assertIsNone(_check_loop_completion(loop, "Still working on it"))

    def test_check_completion_max_iterations_reached(self):
        from hook_stop import _check_loop_completion
        loop = self._make_loop_dict(iteration=5, max_iterations=5, completion_promise=None)
        result = _check_loop_completion(loop, "Some response")
        self.assertEqual(result[0], "exhausted")
        self.assertIn("max iterations", result[1])

    def test_check_completion_no_response_early(self):
        from hook_stop import _check_loop_completion
        loop = self._make_loop_dict(iteration=1, completion_promise=None)
        self.assertIsNone(_check_loop_completion(loop, None))

    def test_check_completion_no_response_late(self):
        from hook_stop import _check_loop_completion
        loop = self._make_loop_dict(iteration=3, completion_promise=None)
        self.assertEqual(_check_loop_completion(loop, None)[0], "exhausted")

    def test_check_completion_promise_trumps_max_iter(self):
        from hook_stop import _check_loop_completion
        loop = self._make_loop_dict(iteration=5, max_iterations=5, completion_promise="DONE")
        self.assertEqual(_check_loop_completion(loop, "Finished <promise>DONE</promise>")[0], "completed")

    def test_check_completion_unlimited(self):
        from hook_stop import _check_loop_completion
        loop = self._make_loop_dict(iteration=100, max_iterations=0, completion_promise=None)
        self.assertIsNone(_check_loop_completion(loop, "Still going"))

    def test_build_loop_context_finds_facts(self):
        from hook_stop import _build_loop_context
        conn = make_db()
        from db import ensure_session
        ensure_session(conn, "test-sess")
        conn.execute(
            "INSERT INTO facts (id, claim, domain, tags, source) "
            "VALUES ('f1', 'Python uses indentation for blocks', 'technical', 'python,syntax', 'test')"
        )
        conn.commit()
        loop = self._make_loop_dict(prompt="Fix the Python indentation error")
        self.assertIn("Python uses indentation", _build_loop_context(conn, loop, "test-sess"))
        conn.close()

    def test_build_loop_context_finds_progress(self):
        from hook_stop import _build_loop_context
        conn = make_db()
        from db import ensure_session, record_message
        ensure_session(conn, "test-sess")
        record_message(conn, "test-sess", "assistant", "Fixed the login bug and added tests")
        conn.commit()
        loop = self._make_loop_dict(prompt="Fix bugs in the login system", started_at="2000-01-01 00:00:00")
        self.assertIn("Fixed the login bug", _build_loop_context(conn, loop, "test-sess"))
        conn.close()

    def test_build_loop_context_empty_when_no_data(self):
        from hook_stop import _build_loop_context
        conn = make_db()
        from db import ensure_session
        ensure_session(conn, "test-sess")
        conn.commit()
        loop = self._make_loop_dict(prompt="something obscure xyzzyx")
        self.assertEqual(_build_loop_context(conn, loop, "test-sess"), "")
        conn.close()

    def test_build_loop_context_always_includes_loop_facts(self):
        from hook_stop import _build_loop_context
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
        loop = self._make_loop_dict(id=1, prompt="Completely unrelated zebra dancing moonlight")
        context = _build_loop_context(conn, loop, "test-sess")
        self.assertIn("Loop facts:", context)
        self.assertIn("L1-progress", context)
        self.assertIn("L1-I1-a", context)
        conn.close()

    def test_build_loop_context_deduplicates_facts(self):
        from hook_stop import _build_loop_context
        conn = make_db()
        from db import ensure_session
        ensure_session(conn, "test-sess")
        conn.execute(
            "INSERT INTO facts (id, claim, domain, tags, source) "
            "VALUES ('L1-I1-a', 'Python indentation matters for blocks', 'loop-discovery', 'python', 'loop-1')"
        )
        conn.commit()
        loop = self._make_loop_dict(id=1, prompt="Fix Python indentation errors")
        context = _build_loop_context(conn, loop, "test-sess")
        self.assertIn("Loop facts:", context)
        self.assertEqual(context.count("L1-I1-a"), 1)
        conn.close()


class TestHandleStopIntegration(unittest.TestCase):

    def _setup_db(self, tmpdir):
        test_db = setup_test_db(tmpdir)
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        from db import ensure_session
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
                from hook_stop import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            msg = conn.execute("SELECT content FROM messages WHERE role = 'assistant'").fetchone()
            self.assertEqual(msg["content"], "I did it")
            conn.close()

    def test_handle_stop_active_loop_blocks_exit(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = self._setup_db(tmpdir)
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
                from hook_stop import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})

            block = json.loads(captured.getvalue())
            self.assertEqual(block["decision"], "block")
            self.assertEqual(block["reason"], "Build feature X")
            self.assertIn("Loop iteration", block["systemMessage"])

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
                from hook_stop import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})

            self.assertEqual(captured.getvalue().strip(), "")
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT status, outcome FROM loops").fetchone()
            self.assertEqual(loop["status"], "completed")
            self.assertEqual(loop["outcome"], "ALL_DONE")
            conn.close()

    def test_handle_stop_loop_exhausted_on_max_iterations(self):
        """Loop at max iteration with no promise should exhaust and allow exit."""
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = self._setup_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_loop
            create_loop(conn, "test-sess", "Do work", 3, None)
            # Advance iteration to 3 (the max)
            conn.execute("UPDATE loops SET iteration = 3 WHERE status = 'active'")
            conn.commit()
            conn.close()

            transcript = os.path.join(tmpdir, "transcript.jsonl")
            with open(transcript, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "go"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Still working"}]}}) + "\n")

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from hook_stop import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})

            # Should not block (no JSON output)
            self.assertEqual(captured.getvalue().strip(), "")
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT status, outcome FROM loops").fetchone()
            self.assertEqual(loop["status"], "exhausted")
            self.assertIn("max iterations", loop["outcome"])
            conn.close()

    def test_handle_stop_loop_exhausted_no_response(self):
        """Loop past iteration 1 with no transcript response should exhaust."""
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = self._setup_db(tmpdir)
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            from db import create_loop
            create_loop(conn, "test-sess", "Do work", 0, None)
            conn.execute("UPDATE loops SET iteration = 3 WHERE status = 'active'")
            conn.commit()
            conn.close()

            # Empty transcript — no assistant response
            transcript = os.path.join(tmpdir, "transcript.jsonl")
            with open(transcript, "w", encoding="utf-8") as f:
                pass  # empty file

            captured = io.StringIO()
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdout", captured):
                from hook_stop import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})

            self.assertEqual(captured.getvalue().strip(), "")
            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            loop = conn.execute("SELECT status, outcome FROM loops").fetchone()
            self.assertEqual(loop["status"], "exhausted")
            conn.close()

    def test_handle_stop_system_message_includes_fact_management(self):
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
                from hook_stop import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})

            sys_msg = json.loads(captured.getvalue())["systemMessage"]
            self.assertIn("progress tracker", sys_msg.lower())
            self.assertIn("INSERT OR REPLACE", sys_msg)
            self.assertIn("Insert", sys_msg)
            self.assertIn("Update", sys_msg)
            self.assertIn("Delete", sys_msg)
            self.assertIn("loop-discovery", sys_msg)

    def test_handle_stop_skipped_for_agent(self):
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = self._setup_db(tmpdir)
            transcript = os.path.join(tmpdir, "transcript.jsonl")
            with open(transcript, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "do work"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done"}]}}) + "\n")
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch.dict(os.environ, {"LARVLING_AGENT": "1"}):
                from hook_stop import handle_stop
                handle_stop({"session_id": "test-sess", "transcript_path": transcript})
            conn = sqlite3.connect(test_db)
            count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()

    def test_handle_stop_main_dispatch(self):
        from hook_stop import main as stop_main
        import db as db_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = self._setup_db(tmpdir)
            transcript = os.path.join(tmpdir, "transcript.jsonl")
            with open(transcript, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "do work"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done"}]}}) + "\n")

            data = json.dumps({"session_id": "test-sess", "transcript_path": transcript})
            with mock.patch.object(db_mod, "DB_PATH", test_db), \
                 mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(data.encode()))):
                stop_main()

            conn = sqlite3.connect(test_db)
            conn.row_factory = sqlite3.Row
            msg = conn.execute("SELECT content FROM messages WHERE role = 'assistant'").fetchone()
            self.assertEqual(msg["content"], "Done")
            conn.close()
