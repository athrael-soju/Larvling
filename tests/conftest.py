"""Shared test fixtures and constants for Larvling test suite."""

import os
import sqlite3
import sys

import pytest

# Add scripts dir to path so we can import modules
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "larvling", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "..", "larvling")

# Known Python stdlib modules (subset covering what Larvling uses + common ones)
STDLIB_MODULES = {
    "os", "sys", "json", "re", "time", "sqlite3", "shutil", "subprocess",
    "urllib", "urllib.request", "html", "io", "tempfile", "unittest",
    "contextlib", "pathlib", "datetime", "collections", "functools",
    "itertools", "hashlib", "math", "string", "textwrap", "copy",
    "typing", "abc", "enum", "dataclasses", "argparse", "logging",
    "asyncio",
}

# Platform-specific APIs that violate portability
PLATFORM_SPECIFIC_APIS = [
    "os.startfile", "winreg", "msvcrt", "_winapi",
    "resource", "grp", "pwd", "fcntl", "termios",
]

# Network modules that should not appear in runtime hooks
NETWORK_MODULES = ["requests", "httpx", "aiohttp", "websocket"]

# Agent scripts are exempt from zero-dep check (they use claude-code-sdk)
AGENT_SCRIPTS = {"agent_facts.py", "agent_summary.py"}


def make_db():
    """Create a fresh in-memory database with schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    from db import create_schema
    create_schema(conn)
    return conn


def get_plugin_files():
    """Get all files in larvling/ excluding __pycache__."""
    files = []
    for root, dirs, filenames in os.walk(PLUGIN_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in filenames:
            files.append(os.path.join(root, f))
    return files


def setup_test_db(tmpdir):
    """Create a test database in a temp directory. Returns the db path."""
    test_db = os.path.join(tmpdir, ".claude", "larvling.db")
    os.makedirs(os.path.dirname(test_db))
    conn = sqlite3.connect(test_db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    from db import create_schema
    create_schema(conn)
    conn.close()
    return test_db
