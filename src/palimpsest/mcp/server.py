"""Palimpsest MCP server (stdio).

Add to any MCP-capable agent (Claude Code, LangGraph, a custom loop):

    {
      "mcpServers": {
        "palimpsest": {
          "command": "palimpsest-mcp",
          "env": { "PALIMPSEST_OWNER": "my-agent" }
        }
      }
    }

The agent's identity comes from ``PALIMPSEST_OWNER`` (one memory space per
agent); the CockroachDB URL resolves as described in ``palimpsest.config``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..db import apply_schema, connect
from ..engine import checkpoints as ckpt
from ..engine.memory import MemoryEngine

OWNER = os.environ.get("PALIMPSEST_OWNER", "default")

mcp = FastMCP(
    "palimpsest",
    instructions=(
        "Persistent memory backed by CockroachDB. Write episodic memories as you work; "
        "retrieve before starting tasks; your memory survives crashes and restarts. "
        "Reconciled memories keep their history as layers (a palimpsest)."
    ),
)

_engine: MemoryEngine | None = None


def engine() -> MemoryEngine:
    global _engine
    if _engine is None:
        conn = connect()
        apply_schema(conn)
        _engine = MemoryEngine(conn)
    return _engine


@mcp.tool()
def memory_write(content: str, tags: str = "") -> str:
    """Record an episodic memory: something that happened, a decision made, or
    feedback received. Write these as you work — they are the raw material that
    nightly consolidation distills into long-term facts."""
    memory_id = engine().write_episodic(OWNER, content, tags)
    return f"remembered ({memory_id})"


@mcp.tool()
def memory_retrieve(query: str, limit: int = 8) -> str:
    """Semantic recall: retrieve the memories most relevant to a query.
    Call this before starting a task to load prior context and preferences."""
    hits = engine().retrieve(OWNER, query, limit=limit)
    if not hits:
        return "no relevant memories"
    return json.dumps(
        [
            {
                "id": m.id,
                "kind": m.kind,
                "content": m.content,
                "confidence": m.confidence,
                "distance": round(m.distance, 4) if m.distance is not None else None,
            }
            for m in hits
        ],
        ensure_ascii=False,
    )


@mcp.tool()
def memory_reflect(memory_id: str) -> str:
    """Show a memory's full provenance: the current layer and every archived
    layer beneath it (what was believed before, and when it changed)."""
    chain = engine().layers(memory_id)
    if not chain:
        return "no such memory"
    return json.dumps(chain, ensure_ascii=False)


@mcp.tool()
def memory_consolidate() -> str:
    """Distill the last 24h of episodic memories into long-term semantic facts.
    Normally runs nightly (AWS Lambda), but can be triggered on demand."""
    count = engine().consolidate(OWNER)
    return f"consolidated {count} facts"


@mcp.tool()
def checkpoint_save(task_id: str, step: str, state: dict[str, Any]) -> str:
    """Snapshot task state after completing a step. After a crash or restart,
    resume from the checkpoint instead of re-doing (and re-paying for) work."""
    ckpt.save(engine().conn, OWNER, task_id, step, state)
    return f"checkpoint saved: {task_id}/{step}"


@mcp.tool()
def checkpoint_load(task_id: str) -> str:
    """Load the most recent checkpoint for a task; returns step and state."""
    result = ckpt.load_latest(engine().conn, OWNER, task_id)
    if result is None:
        return "no checkpoint"
    step, state = result
    return json.dumps({"step": step, "state": state}, ensure_ascii=False)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
