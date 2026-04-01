"""
Larvling Schema Migrations — automated, versioned DDL upgrades.

Each migration is a function that takes a sqlite3.Connection and upgrades
the schema from one version to the next.  run_migrations() chains them
from the current DB version up to SCHEMA_VERSION.
"""

import sqlite3

from db import (
    SCHEMA_VERSION,
    get_schema_version,
    set_schema_version,
    get_current_schema,
    get_desired_schema,
)


# ---------------------------------------------------------------------------
# Migration registry — maps from_version -> (to_version, callable)
#
# Add entries here when SCHEMA_VERSION is bumped.  Example:
#
#   def _v11_to_v12(conn):
#       conn.execute("ALTER TABLE sessions ADD COLUMN foo TEXT")
#
#   MIGRATIONS[11] = (12, _v11_to_v12)
# ---------------------------------------------------------------------------

from typing import Callable

MIGRATIONS: dict[int, tuple[int, Callable]] = {}


class MigrationError(Exception):
    """Raised when a migration step fails."""
    pass


def run_migrations(conn: sqlite3.Connection) -> int:
    """Run all pending migrations from current version to SCHEMA_VERSION.

    Args:
        conn: Open database connection (caller manages backup).

    Returns:
        Number of migration steps executed (0 if already current).

    Raises:
        MigrationError: If a migration step fails or the chain is broken.
    """
    current = get_schema_version(conn)
    target = SCHEMA_VERSION

    if current == target:
        return 0

    if current > target:
        raise MigrationError(
            f"Database version ({current}) is newer than code ({target}). "
            f"Is the plugin out of date?"
        )

    steps = 0
    version = current

    while version < target:
        if version not in MIGRATIONS:
            raise MigrationError(
                f"No migration registered for version {version} -> {version + 1}. "
                f"Cannot migrate from v{current} to v{target}."
            )

        to_version, migrate_fn = MIGRATIONS[version]

        if to_version != version + 1:
            raise MigrationError(
                f"Migration gap: v{version} -> v{to_version} (expected v{version + 1})."
            )

        try:
            migrate_fn(conn)
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise MigrationError(
                f"Migration v{version} -> v{to_version} failed: {e}"
            ) from e

        set_schema_version(conn, to_version)
        steps += 1
        version = to_version

    # Post-migration verification: compare live schema to desired
    live = _normalize(get_current_schema(conn))
    desired = _normalize(get_desired_schema())

    if live != desired:
        raise MigrationError(
            "Schema mismatch after migration. Live schema does not match desired.\n"
            f"Live:\n{get_current_schema(conn)}\n\n"
            f"Desired:\n{get_desired_schema()}"
        )

    return steps


def _normalize(sql: str) -> str:
    """Normalize SQL for comparison (collapse whitespace, sort statements).

    Sorting ensures that index/table creation order in sqlite_master
    (which reflects insertion order) doesn't cause false mismatches
    against the desired schema (which reflects source-code order).
    """
    stmts = [" ".join(s.split()) for s in sql.strip().split(";") if s.strip()]
    return "\n".join(sorted(stmts))
