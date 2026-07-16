"""Nightly consolidation job — AWS Lambda handler.

Runs on an EventBridge schedule (e.g. ``cron(0 3 * * ? *)``): for every agent
that produced episodic memories in the last 24h, distill them into long-term
semantic facts, then apply the forgetting curve. Off-peak, cheap tokens.

Deployment (documented; see docs/):
- container-image Lambda (psycopg needs a linux wheel), arm64, 512 MB
- env: PALIMPSEST_DB_URL (CockroachDB URI), PALIMPSEST_LLM_MODEL
- IAM: bedrock:InvokeModel only — least privilege
- trigger: EventBridge Scheduler, nightly

The handler is idempotent: re-running consolidates only what is still fresh,
and duplicate facts merely reinforce existing memories.
"""

from __future__ import annotations

from typing import Any

from ..db import connect
from ..engine.memory import MemoryEngine


def handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    conn = connect()
    try:
        engine = MemoryEngine(conn)
        owners = [
            r[0]
            for r in conn.execute(
                """SELECT DISTINCT owner_id FROM memories
                   WHERE kind = 'episodic' AND archived = false
                     AND created_at >= now() - INTERVAL '24 hours'"""
            ).fetchall()
        ]
        results = {owner: engine.consolidate(owner) for owner in owners}
        archived = engine.decay()
        return {"owners": len(owners), "facts": results, "archived": archived}
    finally:
        conn.close()


if __name__ == "__main__":
    print(handler())
