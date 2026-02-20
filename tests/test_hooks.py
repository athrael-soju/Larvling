"""Hook tests — transcript parsing, hook_prompt, hook_stop, hook_end, and dispatch."""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from conftest import make_db, setup_test_db


class TestTranscriptParsing(unittest.TestCase):

    def test_strip_ide_tags_basic(self):
        from transcript import strip_ide_tags
        text = '<ide_opened_file>/path/to/file.py</ide_opened_file> hello world'
        self.assertEqual(strip_ide_tags(text), "hello world")

    def test_strip_ide_tags_selection(self):
        from transcript import strip_ide_tags
        text = '<ide_selection>some selected text</ide_selection> actual prompt'
        self.assertEqual(strip_ide_tags(text), "actual prompt")

    def test_strip_ide_tags_multiple(self):
        from transcript import strip_ide_tags
        text = (
            '<ide_opened_file>file1.py</ide_opened_file> '
            '<ide_selection>sel</ide_selection> prompt here'
        )
        self.assertEqual(strip_ide_tags(text), "prompt here")

    def test_strip_ide_tags_preserves_content(self):
        from transcript import strip_ide_tags
        self.assertEqual(strip_ide_tags("just a normal prompt"), "just a normal prompt")

    def test_strip_ide_tags_empty(self):
        from transcript import strip_ide_tags
        self.assertEqual(strip_ide_tags(""), "")

    def test_is_real_user_message_text(self):
        from transcript import _is_real_user_message
        self.assertTrue(_is_real_user_message(
            {"type": "user", "message": {"content": "hello"}}))

    def test_is_real_user_message_tool_result(self):
        from transcript import _is_real_user_message
        self.assertFalse(_is_real_user_message(
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}))

    def test_is_real_user_message_non_user(self):
        from transcript import _is_real_user_message
        self.assertFalse(_is_real_user_message(
            {"type": "assistant", "message": {"content": "hi"}}))

    def test_is_real_user_message_list_without_tool_result(self):
        from transcript import _is_real_user_message
        self.assertTrue(_is_real_user_message(
            {"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}))

    def test_parse_last_turn_empty(self):
        from transcript import parse_last_turn
        text, tools = parse_last_turn(None)
        self.assertIsNone(text)
        self.assertEqual(tools, {})

    def test_parse_last_turn_nonexistent(self):
        from transcript import parse_last_turn
        text, tools = parse_last_turn("/nonexistent/path.jsonl")
        self.assertIsNone(text)
        self.assertEqual(tools, {})

    def test_parse_last_turn_simple(self):
        from transcript import parse_last_turn
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
        from transcript import parse_last_turn
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
        from transcript import parse_last_turn
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


class TestMainDispatchErrors(unittest.TestCase):

    def test_empty_stdin_noop(self):
        from hook_prompt import main as prompt_main
        from hook_stop import main as stop_main
        from hook_end import main as end_main
        for main_fn in (prompt_main, stop_main, end_main):
            with mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(b""))):
                main_fn()

    def test_invalid_json_noop(self):
        from hook_prompt import main as prompt_main
        from hook_stop import main as stop_main
        from hook_end import main as end_main
        for main_fn in (prompt_main, stop_main, end_main):
            with mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(b"not json{{{"))):
                main_fn()
