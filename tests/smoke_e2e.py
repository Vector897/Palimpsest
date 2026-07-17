"""Live end-to-end smoke test against real CockroachDB + Bedrock.

Run from the repo root (or project root containing .crdb-connection):

    python tests/smoke_e2e.py

Exercises: schema apply, episodic writes with real Titan embeddings,
two-stage vector retrieval, consolidation via Bedrock LLM,
arbitration layering, decay, checkpoints, and the audit trail.
Uses a throwaway owner_id and cleans up after itself.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest import MemoryEngine  # noqa: E402
from palimpsest.db import apply_schema, connect  # noqa: E402
from palimpsest.engine import checkpoints  # noqa: E402

OWNER = f"smoke-{uuid.uuid4().hex[:8]}"


def main() -> None:
    conn = connect()
    apply_schema(conn)
    print("1. schema applied")

    eng = MemoryEngine(conn)

    eng.write_episodic(OWNER, "Reader marked a story about Postgres async I/O as important.", "triage")
    eng.write_episodic(OWNER, "Reader ignored a roundup of the year's best productivity apps.", "triage")
    eng.write_episodic(OWNER, "Reader marked a story about Rust async traits as important.", "triage")
    print("2. wrote 3 episodic memories (real Titan embeddings)")

    hits = eng.retrieve(OWNER, "which topics does the reader care about?")
    assert hits, "retrieval returned nothing"
    print(f"3. retrieval: {len(hits)} hits, best dist={hits[0].distance:.4f}: {hits[0].content[:60]}")

    facts = eng.consolidate(OWNER)
    print(f"4. consolidation via Bedrock LLM: {facts} semantic facts distilled")

    sem = conn.execute(
        "SELECT id, content FROM memories WHERE owner_id=%s AND kind='semantic' AND archived=false LIMIT 1",
        (OWNER,),
    ).fetchone()
    if sem:
        new_id = eng.arbitrate(OWNER, str(sem[0]), sem[1],
                               "The reader now prioritizes managed cloud services over self-hosted tooling.")
        chain = eng.layers(new_id)
        assert len(chain) >= 2 and chain[1]["archived"], "palimpsest layering failed"
        print(f"5. arbitration: new layer over old, chain depth={len(chain)}, old layer archived but readable")

    archived = eng.decay(OWNER)
    print(f"6. decay pass done (archived {archived} cold memories)")

    checkpoints.save(conn, OWNER, "task-1", "step-2", {"progress": 0.5})
    checkpoints.save(conn, OWNER, "task-1", "step-2", {"progress": 0.9})
    step, state = checkpoints.load_latest(conn, OWNER, "task-1")
    assert state["progress"] == 0.9
    print(f"7. checkpoint upsert+resume: step={step} state={state}")

    n = conn.execute("SELECT count(*) FROM audit_log WHERE owner_id=%s", (OWNER,)).fetchone()[0]
    print(f"8. audit trail: {n} entries")

    for table in ("memories", "checkpoints", "audit_log"):
        conn.execute(f"DELETE FROM {table} WHERE owner_id = %s", (OWNER,))
    conn.close()
    print("9. cleanup done — SMOKE PASSED")


if __name__ == "__main__":
    main()
