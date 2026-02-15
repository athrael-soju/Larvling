"""Shared database helpers for Larvling hook scripts."""

import json
import os
import sqlite3

PROJECT_ROOT = os.getcwd()
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "larvling.db")


def get_db():
    """Open a connection to larvling.db with WAL mode."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def imprint(conn, session_id, event_type, content, metadata=None):
    """Record an imprint and commit."""
    conn.execute(
        "INSERT INTO imprints (session_id, event_type, content, metadata) VALUES (?, ?, ?, ?)",
        (session_id, event_type, content, json.dumps(metadata) if metadata else None),
    )
    conn.commit()
