"""Live MCP smoke test: spawns the Palimpsest MCP server over stdio (exactly
how a real agent would) and exercises every tool.

    python tests/smoke_mcp.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

OWNER = f"mcp-smoke-{uuid.uuid4().hex[:8]}"


async def call(session: ClientSession, tool: str, args: dict) -> str:
    result = await session.call_tool(tool, args)
    return result.content[0].text


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "palimpsest.mcp.server"],
        env={**os.environ, "PALIMPSEST_OWNER": OWNER},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = [t.name for t in (await session.list_tools()).tools]
            print(f"1. tools exposed: {tools}")
            assert {"memory_write", "memory_retrieve", "memory_reflect",
                    "memory_consolidate", "checkpoint_save", "checkpoint_load"} <= set(tools)

            r = await call(session, "memory_write",
                           {"content": "User prefers concise briefings in the morning.", "tags": "pref"})
            print(f"2. memory_write: {r}")

            r = await call(session, "memory_retrieve", {"query": "how does the user like reports?"})
            hits = json.loads(r)
            assert hits and "concise" in hits[0]["content"]
            print(f"3. memory_retrieve: {len(hits)} hits, best: {hits[0]['content'][:50]}")

            r = await call(session, "memory_reflect", {"memory_id": hits[0]["id"]})
            print(f"4. memory_reflect: chain depth {len(json.loads(r))}")

            r = await call(session, "checkpoint_save",
                           {"task_id": "t1", "step": "s1", "state": {"done": 2}})
            print(f"5. {r}")
            r = await call(session, "checkpoint_load", {"task_id": "t1"})
            assert json.loads(r)["state"]["done"] == 2
            print(f"6. checkpoint_load: {r}")

    # cleanup with a direct connection
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from palimpsest.db import connect
    conn = connect()
    for table in ("memories", "checkpoints", "audit_log"):
        conn.execute(f"DELETE FROM {table} WHERE owner_id = %s", (OWNER,))
    conn.close()
    print("7. cleanup done — MCP SMOKE PASSED")


if __name__ == "__main__":
    asyncio.run(main())
