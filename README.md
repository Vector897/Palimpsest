# Palimpsest — agent memory that survives, on CockroachDB

> A palimpsest is a manuscript page scraped clean and written over — with the earlier writing still faintly visible beneath.
> That is how agent memory should work: **new knowledge layers over old, and history is never destroyed.**

Palimpsest is a **production-grade memory layer for AI agents**, backed by CockroachDB.
Any agent — Claude Code, LangGraph, a custom loop — plugs in through **MCP** and gets:

- **Episodic → semantic lifecycle** — every task execution writes episodic memory; a nightly consolidation job (AWS Lambda + Bedrock) distills recurring facts into long-term semantic memory.
- **Temporal conflict arbitration** — when new facts contradict old ones, Palimpsest writes a reconciliation with explicit time sense ("X held before May, updated to Y since") instead of a blind overwrite. Old layers remain queryable — hence the name.
- **Forgetting curve** — memory heat = access frequency × recency decay; cold memories are demoted out of the retrieval index (archived, never destroyed).
- **Two-stage retrieval** — SQL prefix filtering (owner/tags) then ANN search on CockroachDB's distributed vector index.
- **Crash-safe by construction** — memories, checkpoints, and audit log live in a distributed SQL database that survives node and region failure. Kill the agent; its memory is intact. Paid tokens are never spent twice.

Built for the [CockroachDB × AWS Hackathon](https://cockroachdb-ai.devpost.com/) — *Agents that think. Agents that act. Agents that remember.*

## Architecture

```
 any agent ──MCP──▶ Palimpsest server ──▶ CockroachDB Cloud
                       │                    ├─ memories (VECTOR INDEX, cosine)
                       │                    ├─ checkpoints
                       ▲                    └─ audit_log
                       │
 AWS Lambda (EventBridge nightly) ── consolidation / arbitration / decay
                       │
 Amazon Bedrock ── Titan embeddings + LLM for consolidation
```

## Status

Work in progress — hackathon submission period (June 30 – Aug 18, 2026).

## Provenance disclosure

The memory-lifecycle *concepts* (episodic→semantic consolidation, temporal arbitration,
heat decay, two-stage retrieval) were first prototyped by the author in
[JarvisQwen](https://github.com/Vector897/JarvisQwen) as a ~150-line SQLite +
keyword-matching module. Palimpsest is a ground-up rewrite created during the
submission period: new codebase, CockroachDB distributed storage, real vector
retrieval, MCP interface, and AWS-native consolidation. No code is shared.

## License

[Apache-2.0](LICENSE)
