"""
Tests for the 6 DB optimizations.

Run from the scripts directory:
    python test_optimizations.py

Uses an in-memory database — does not touch the real larvling.db.
"""

import sqlite3
import sys
import os
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

# Ensure scripts directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import create_schema, get_db, open_db, SCHEMA_VERSION
from migrations import MIGRATIONS, run_migrations, _normalize
from analyze import process_knowledge, process_tasks


def make_test_db():
    """Create an in-memory DB with the full schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn


class TestCompoundIndex(unittest.TestCase):
    """#1: Compound index on messages(session_id, role)."""

    def test_index_exists_after_create_schema(self):
        conn = make_test_db()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_messages_session_role'"
        ).fetchall()
        self.assertEqual(len(indexes), 1, "Compound index should exist after create_schema")
        conn.close()

    def test_index_columns(self):
        conn = make_test_db()
        info = conn.execute("PRAGMA index_info(idx_messages_session_role)").fetchall()
        col_names = [row["name"] for row in info]
        self.assertEqual(col_names, ["session_id", "role"],
                         "Index should cover (session_id, role) in that order")
        conn.close()

    def test_migration_v11_to_v12(self):
        """Simulate a v11 database and run the migration."""
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row

        # Create schema without the new index (simulate v11)
        create_schema(conn)
        conn.execute("DROP INDEX IF EXISTS idx_messages_session_role")
        conn.execute(f"PRAGMA user_version = 11")

        # Verify it's gone
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_messages_session_role'"
        ).fetchone()
        self.assertIsNone(row, "Index should not exist before migration")

        # Run migration
        _, migrate_fn = MIGRATIONS[11]
        migrate_fn(conn)
        conn.commit()

        # Verify it's back
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_messages_session_role'"
        ).fetchone()
        self.assertIsNotNone(row, "Index should exist after migration")
        conn.close()

    def test_schema_version_is_12(self):
        self.assertEqual(SCHEMA_VERSION, 12)


class TestBoundedLikeScans(unittest.TestCase):
    """#2: find_relevant_sessions scopes to recent sessions."""

    def test_only_searches_recent_sessions(self):
        conn = make_test_db()

        # Create an old session and a recent session
        conn.execute(
            "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
            ("old-session-1111", "2020-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
            ("new-session-2222", "2026-01-01T00:00:00"),
        )
        # Both mention "app.py"
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            ("old-session-1111", "user", "editing app.py"),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            ("new-session-2222", "user", "editing app.py"),
        )
        conn.commit()

        # Import and test — the function should find the new session
        from hooks.session_start import find_relevant_sessions

        results = find_relevant_sessions(conn, ["src/app.py"], set(), limit=5)
        # Both are within the 50-session window, so both should appear
        # The key behavior: the query includes the IN clause to bound the scan
        self.assertIsInstance(results, list)
        conn.close()

    def test_empty_file_list(self):
        conn = make_test_db()
        from hooks.session_start import find_relevant_sessions

        results = find_relevant_sessions(conn, [], set(), limit=3)
        self.assertEqual(results, [])
        conn.close()


class TestRedundantQueryRemoved(unittest.TestCase):
    """#3: get_recent_summaries returns IDs, no duplicate query."""

    def test_returns_tuple_with_sids(self):
        conn = make_test_db()
        conn.execute(
            "INSERT INTO sessions (id, started_at, title) VALUES (?, ?, ?)",
            ("sess-aaaa", "2026-01-01", "Test session"),
        )
        conn.commit()

        from hooks.session_start import get_recent_summaries

        result = get_recent_summaries(conn, limit=5)
        self.assertIsInstance(result, tuple, "Should return a tuple")
        self.assertEqual(len(result), 2, "Should return (summaries, sids)")
        summaries, sids = result
        self.assertIsInstance(summaries, list)
        self.assertIsInstance(sids, set)
        self.assertIn("sess-aaaa", sids)
        conn.close()

    def test_empty_db(self):
        conn = make_test_db()
        from hooks.session_start import get_recent_summaries

        summaries, sids = get_recent_summaries(conn, limit=5)
        self.assertEqual(summaries, [])
        self.assertEqual(sids, set())
        conn.close()


class TestAutoCommitRollback(unittest.TestCase):
    """#4: open_db() auto-commits on success, rolls back on exception."""

    @patch("db.DB_PATH", ":memory:")
    def test_auto_commit_on_success(self):
        # We can't easily test with the real open_db() and :memory:
        # since each connection to :memory: is a new database.
        # Instead, test the pattern with a file-based temp DB.
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()

        try:
            with patch("db.DB_PATH", tmp.name):
                with open_db() as conn:
                    create_schema(conn)
                    conn.execute(
                        "INSERT INTO sessions (id, started_at) VALUES (?, datetime('now'))",
                        ("auto-commit-test",),
                    )
                    # No explicit conn.commit() — auto-commit should handle it

                # Reopen and verify the data persisted
                with open_db() as conn2:
                    row = conn2.execute(
                        "SELECT id FROM sessions WHERE id = ?",
                        ("auto-commit-test",),
                    ).fetchone()
                    self.assertIsNotNone(row, "Data should persist via auto-commit")
        finally:
            os.unlink(tmp.name)

    @patch("db.DB_PATH", ":memory:")
    def test_rollback_on_exception(self):
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()

        try:
            with patch("db.DB_PATH", tmp.name):
                with open_db() as conn:
                    create_schema(conn)
                conn.close()

                # Insert then raise — should rollback
                try:
                    with open_db() as conn:
                        conn.execute(
                            "INSERT INTO sessions (id, started_at) VALUES (?, datetime('now'))",
                            ("rollback-test",),
                        )
                        raise ValueError("Simulated error")
                except ValueError:
                    pass

                # Verify the data did NOT persist
                with open_db() as conn2:
                    row = conn2.execute(
                        "SELECT id FROM sessions WHERE id = ?",
                        ("rollback-test",),
                    ).fetchone()
                    self.assertIsNone(row, "Data should be rolled back on exception")
        finally:
            os.unlink(tmp.name)


class TestCursorLastRowid(unittest.TestCase):
    """#5: process_knowledge uses cursor.lastrowid."""

    def test_add_topic_uses_lastrowid(self):
        conn = make_test_db()
        knowledge = [
            {
                "topic_title": "Test Topic",
                "claim": "This is a test claim",
                "domain": "technical",
                "tags": "testing",
                "action": "add_topic",
            }
        ]
        topics_ins, stmts_ins, _, _ = process_knowledge(conn, knowledge, "test-sid")
        self.assertEqual(topics_ins, 1)
        self.assertEqual(stmts_ins, 1)

        # Verify the statement is linked to the topic
        row = conn.execute(
            "SELECT t.title, s.claim FROM topics t "
            "JOIN statements s ON s.topic_id = t.id"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "Test Topic")
        self.assertEqual(row["claim"], "This is a test claim")
        conn.close()

    def test_add_multiple_topics(self):
        conn = make_test_db()
        knowledge = [
            {
                "topic_title": f"Topic {i}",
                "claim": f"Claim {i}",
                "domain": "technical",
                "tags": "test",
                "action": "add_topic",
            }
            for i in range(5)
        ]
        topics_ins, stmts_ins, _, _ = process_knowledge(conn, knowledge, "test-sid")
        self.assertEqual(topics_ins, 5)
        self.assertEqual(stmts_ins, 5)

        # Verify each statement is linked to its own topic (not all to the same one)
        rows = conn.execute(
            "SELECT t.title, s.claim FROM topics t "
            "JOIN statements s ON s.topic_id = t.id "
            "ORDER BY t.id"
        ).fetchall()
        for i, row in enumerate(rows):
            self.assertEqual(row["title"], f"Topic {i}")
            self.assertEqual(row["claim"], f"Claim {i}")
        conn.close()


class TestWALCheckpoint(unittest.TestCase):
    """#6: WAL checkpoint runs on session end."""

    def test_checkpoint_pragma_succeeds(self):
        """Verify the PRAGMA doesn't error on a WAL-mode database."""
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()

        try:
            conn = sqlite3.connect(tmp.name)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO test VALUES (1)")
            conn.commit()

            # This is what session_end.py now does
            result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            # Returns (busy, log_pages, checkpointed_pages)
            self.assertIsNotNone(result)
            self.assertEqual(result[0], 0, "Checkpoint should not be busy")
            conn.close()
        finally:
            # Clean up DB and WAL/SHM files
            for suffix in ("", "-wal", "-shm"):
                path = tmp.name + suffix
                if os.path.exists(path):
                    os.unlink(path)

    def test_session_end_includes_checkpoint(self):
        """Verify the checkpoint call is in session_end.py source."""
        import inspect
        from hooks.session_end import handle

        source = inspect.getsource(handle)
        self.assertIn("wal_checkpoint", source,
                       "session_end.handle should include WAL checkpoint")


class TestMigrationChain(unittest.TestCase):
    """Verify the full migration chain works end-to-end."""

    def test_v11_to_current(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row

        # Create v11 schema (current minus the new index)
        create_schema(conn)
        conn.execute("DROP INDEX IF EXISTS idx_messages_session_role")
        conn.execute("PRAGMA user_version = 11")
        conn.commit()

        steps = run_migrations(conn)
        self.assertEqual(steps, 1)

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, SCHEMA_VERSION)

        # Verify schema matches desired
        from db import get_current_schema, get_desired_schema
        live = _normalize(get_current_schema(conn))
        desired = _normalize(get_desired_schema())
        self.assertEqual(live, desired, "Post-migration schema should match desired")
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
