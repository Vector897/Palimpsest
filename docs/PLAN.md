# Palimpsest — build plan

Hackathon: [CockroachDB × AWS](https://cockroachdb-ai.devpost.com/) · deadline **2026-08-18 17:00 EDT** · judged on: agent-memory design, technical execution, real-world impact, production readiness, innovation.

## Requirement mapping

| Requirement | How Palimpsest satisfies it |
|---|---|
| ≥2 CockroachDB tools | ① Distributed vector index (semantic retrieval, cosine) ② CockroachDB Cloud MCP server (agent introspects its own memory DB) — bonus: ③ PR to `cockroachdb-skills` (memory-schema management skill) |
| ≥1 AWS service | ① Bedrock (Titan embeddings + LLM for consolidation/arbitration) ② Lambda + EventBridge (nightly consolidation) |
| Public OSS repo + license | Apache-2.0; repo flips private→public before submission (history proves in-period work) |
| Demo URL + ≤3 min video | Paper-triage demo agent + kill/recover scene |

## Components

1. **Core engine** (`src/palimpsest/engine/`) — write_episodic / retrieve (two-stage: SQL prefix → ANN) / consolidate / arbitrate / decay. Python, psycopg3 against CRDB.
2. **MCP server** (`src/palimpsest/mcp/`) — tools: `memory_write`, `memory_retrieve`, `memory_reflect` (what do I know about X, with provenance layers), `checkpoint_save/load`.
3. **Consolidation Lambda** (`src/palimpsest/adapters/`) — EventBridge nightly: episodic→semantic distillation via Bedrock, temporal arbitration on conflict, heat decay + archival.
4. **Demo agent** (`demo/`) — thin paper-triage agent: subscribe topic → morning triage → user marks important/ignore → semantic memory shifts next-day decisions. Video money-shot: `kill -9` the agent, restart, memory + checkpoint intact from CRDB.

## Milestones

- **Spike (ASAP, blocks everything)**: free-tier CRDB cluster; verify `feature.vector_index.enabled` works on Basic tier; insert 1k vectors, `CREATE VECTOR INDEX` with owner_id prefix column, cosine query. Fallback: Standard trial credits.
- **W1 (~07-16 → 07-23)**: core engine + schema against live CRDB; Bedrock embeddings wired.
- **W2 (~07-24 → 07-31)**: MCP server; consolidation/arbitration; Lambda deploy.
- **W3 (~08-01 → 08-08)**: demo agent; Cloud MCP server integration; cockroachdb-skills PR. (DataHub hackathon deadline 08-10 — buffer for context switch.)
- **W4 (08-11 → 08-17)**: polish, architecture diagram, video, Devpost submission text; flip repo public. Submit 08-17, one-day buffer.

## Open verifications

- [ ] Vector index available on Basic (free) tier? Exact `CREATE VECTOR INDEX` prefix-column syntax?
- [ ] Cloud MCP server availability/plan gating; connection flow from Claude Code.
- [ ] Titan Embeddings V2 dims (1024 default; 256/512 options) — pick after recall test.
- [ ] Bedrock region with both Titan + Claude available (us-east-1 likely).

## Provenance rule (compliance)

Rules require the project be newly created during the submission period (06-30 → 08-18); pre-existing work must be disclosed. Concepts come from JarvisQwen's memory module (~150 LOC, SQLite + keyword match); **no code is copied** — this is a ground-up rewrite. Disclosure lives in README § Provenance.
