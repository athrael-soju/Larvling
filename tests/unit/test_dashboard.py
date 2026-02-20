"""Dashboard tests — rendering functions and revision tracking."""

import json
import unittest

from conftest import make_db


class TestDashboardRendering(unittest.TestCase):

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
        html = render_page("<div>sidebar</div>", "<div>details</div>", 42)
        self.assertNotIn("{{SIDEBAR}}", html)
        self.assertNotIn("{{DETAILS}}", html)
        self.assertNotIn("{{REVISION}}", html)
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
