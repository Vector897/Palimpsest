"""Crash-safe task checkpoints.

Agents snapshot pipeline state after each step; after a crash they resume from
the last checkpoint instead of re-spending tokens. State lives in CockroachDB,
so recovery works from any machine.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg


def save(conn: psycopg.Connection, owner_id: str, task_id: str, step: str,
         state: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO checkpoints (owner_id, task_id, step, state)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (owner_id, task_id, step)
           DO UPDATE SET state = excluded.state, created_at = now()""",
        (owner_id, task_id, step, json.dumps(state)),
    )


def load_latest(conn: psycopg.Connection, owner_id: str, task_id: str
                ) -> tuple[str, dict[str, Any]] | None:
    """Return (step, state) of the most recent checkpoint, or None."""
    row = conn.execute(
        """SELECT step, state FROM checkpoints
           WHERE owner_id = %s AND task_id = %s
           ORDER BY created_at DESC LIMIT 1""",
        (owner_id, task_id),
    ).fetchone()
    return (row[0], row[1]) if row else None
