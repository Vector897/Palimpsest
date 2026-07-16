"""Database access and schema management for CockroachDB."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg

from .config import settings

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


def connect(autocommit: bool = True) -> psycopg.Connection:
    """Open a connection to the CockroachDB cluster."""
    return psycopg.connect(settings.db_url, autocommit=autocommit)


@contextmanager
def session() -> Iterator[psycopg.Cursor]:
    """A cursor wrapped in a transaction: commits on success, rolls back on error."""
    with psycopg.connect(settings.db_url) as conn:
        with conn.cursor() as cur:
            yield cur


def apply_schema(conn: psycopg.Connection | None = None) -> None:
    """Apply db/schema.sql (idempotent — everything is IF NOT EXISTS)."""
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute("SET CLUSTER SETTING feature.vector_index.enabled = true")
        conn.execute(sql)
    finally:
        if own:
            conn.close()


if __name__ == "__main__":
    apply_schema()
    print("schema applied")
