-- Palimpsest schema — CockroachDB
-- Verified 2026-07-16 against CockroachDB Cloud Basic (v26.2.1): VECTOR(1024),
-- prefix-column vector index, cosine ANN, and EXPLAIN-confirmed index usage all work.
-- Requires: SET CLUSTER SETTING feature.vector_index.enabled = true;

CREATE TABLE IF NOT EXISTS memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    STRING NOT NULL,
    kind        STRING NOT NULL CHECK (kind IN ('episodic', 'semantic')),
    content     STRING NOT NULL,
    tags        STRING NOT NULL DEFAULT '',
    embedding   VECTOR(1024),            -- Titan Text Embeddings V2, 1024-dim
    heat        FLOAT8 NOT NULL DEFAULT 1.0,
    confidence  FLOAT8 NOT NULL DEFAULT 0.5,
    archived    BOOL NOT NULL DEFAULT false,
    supersedes  UUID REFERENCES memories (id),  -- palimpsest layer: the memory this reconciliation wrote over
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Two-stage retrieval: owner_id prefix filter, then cosine ANN.
CREATE VECTOR INDEX IF NOT EXISTS memories_embedding_idx
    ON memories (owner_id, embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS memories_owner_kind_idx
    ON memories (owner_id, kind, archived, created_at DESC);

CREATE TABLE IF NOT EXISTS checkpoints (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    STRING NOT NULL,
    task_id     STRING NOT NULL,
    step        STRING NOT NULL,
    state       JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_id, task_id, step)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    STRING NOT NULL,
    action      STRING NOT NULL,          -- write_episodic | retrieve | consolidate | arbitrate | decay | checkpoint
    detail      JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
