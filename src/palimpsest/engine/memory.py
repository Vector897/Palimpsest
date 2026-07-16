"""The Palimpsest memory engine.

Five operations over a CockroachDB-backed memory store:

- ``write_episodic``  — record what happened (one row per experience)
- ``retrieve``        — two-stage recall: SQL prefix filter, then cosine ANN
- ``consolidate``     — distill recent episodes into long-term semantic facts
- ``arbitrate``       — reconcile a new fact with a conflicting old one; the old
                        layer is archived (never deleted) and linked via
                        ``supersedes`` — the palimpsest layering
- ``decay``           — forgetting curve: heat decays, cold memories leave the
                        retrieval index (archived, not destroyed)

Every operation writes an audit_log row. All state lives in CockroachDB, so a
crashed agent recovers its full memory by reconnecting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg

from ..config import settings
from .embeddings import TitanEmbedder, to_vector_literal
from .llm import BedrockClaude


@dataclass
class Memory:
    id: str
    kind: str
    content: str
    tags: str
    heat: float
    confidence: float
    distance: float | None = None


CONSOLIDATE_PROMPT = """\
Below are work-log fragments from an AI agent over the last 24 hours.
Extract 1-5 facts or patterns worth remembering long-term (stable user
preferences, recurring themes, decisions that will matter later).
Preserve concrete technical terms (method names, domains, topics) verbatim —
abstractions like "advanced techniques" lose the signal retrieval needs.
One per line, conclusions only, no numbering:

{episodes}"""

ARBITRATE_PROMPT = """\
Two records about the same topic, from different points in time, may conflict.
Write ONE sentence that reconciles them with explicit time sense
(e.g. "X was A before <time>, updated to B since"):

Older record: {old}
Newer record: {new}"""


class MemoryEngine:
    def __init__(
        self,
        conn: psycopg.Connection,
        embedder: TitanEmbedder | None = None,
        llm: BedrockClaude | None = None,
    ):
        self.conn = conn
        self.embedder = embedder or TitanEmbedder()
        self.llm = llm or BedrockClaude()

    # -- write ------------------------------------------------------------

    def write_episodic(self, owner_id: str, content: str, tags: str = "") -> str:
        vec = to_vector_literal(self.embedder.embed(content))
        row = self.conn.execute(
            """INSERT INTO memories (owner_id, kind, content, tags, embedding)
               VALUES (%s, 'episodic', %s, %s, %s::vector) RETURNING id""",
            (owner_id, content[:4000], tags, vec),
        ).fetchone()
        self._audit(owner_id, "write_episodic", {"memory_id": str(row[0]), "tags": tags})
        return str(row[0])

    # -- read -------------------------------------------------------------

    def retrieve(
        self,
        owner_id: str,
        query: str,
        limit: int = 8,
        kinds: tuple[str, ...] = ("episodic", "semantic"),
    ) -> list[Memory]:
        """Two-stage retrieval: prefix filter (owner, kind, live) then cosine ANN.

        The prefix columns of the vector index make the filter part of the index
        scan itself. Retrieved memories gain heat (they are 'touched').
        """
        qvec = to_vector_literal(self.embedder.embed(query))
        rows = self.conn.execute(
            """SELECT id, kind, content, tags, heat, confidence,
                      embedding <=> %s::vector AS dist
               FROM memories
               WHERE owner_id = %s AND archived = false AND kind = ANY(%s)
               ORDER BY embedding <=> %s::vector
               LIMIT %s""",
            (qvec, owner_id, list(kinds), qvec, limit),
        ).fetchall()
        hits = [Memory(str(r[0]), r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows]
        if hits:
            self.conn.execute(
                "UPDATE memories SET heat = heat + 1.0 WHERE id = ANY(%s)",
                ([m.id for m in hits],),
            )
        self._audit(owner_id, "retrieve", {"query": query[:200], "hits": len(hits)})
        return hits

    # -- consolidate ------------------------------------------------------

    def consolidate(self, owner_id: str, min_episodes: int = 3) -> int:
        """Distill the last 24h of episodic memory into semantic facts.

        For each distilled fact, the nearest existing semantic memory decides
        its fate (cosine distance bands):
        - nearly identical  → reinforce the existing memory (confidence + heat)
        - same topic        → arbitrate: write a reconciled layer over the old
        - unrelated         → insert as a new semantic memory
        """
        rows = self.conn.execute(
            """SELECT content FROM memories
               WHERE owner_id = %s AND kind = 'episodic' AND archived = false
                 AND created_at >= now() - INTERVAL '24 hours'
               ORDER BY created_at DESC LIMIT 40""",
            (owner_id,),
        ).fetchall()
        if len(rows) < min_episodes:
            return 0

        episodes = "\n---\n".join(r[0][:500] for r in rows)
        raw = self.llm.complete(CONSOLIDATE_PROMPT.format(episodes=episodes))
        count = 0
        for line in raw.splitlines():
            fact = line.strip().lstrip("0123456789.-• ")
            if len(fact) < 8:
                continue
            self._absorb_fact(owner_id, fact)
            count += 1
        self._audit(owner_id, "consolidate", {"episodes": len(rows), "facts": count})
        return count

    def _absorb_fact(self, owner_id: str, fact: str) -> None:
        vec = to_vector_literal(self.embedder.embed(fact))
        nearest = self.conn.execute(
            """SELECT id, content, embedding <=> %s::vector AS dist
               FROM memories
               WHERE owner_id = %s AND kind = 'semantic' AND archived = false
               ORDER BY embedding <=> %s::vector LIMIT 1""",
            (vec, owner_id, vec),
        ).fetchone()

        if nearest and nearest[2] < settings.duplicate_below:
            self.conn.execute(
                """UPDATE memories
                   SET confidence = LEAST(1.0, confidence + 0.1),
                       heat = heat + 1.0, updated_at = now()
                   WHERE id = %s""",
                (nearest[0],),
            )
        elif nearest and nearest[2] < settings.conflict_below:
            self.arbitrate(owner_id, str(nearest[0]), nearest[1], fact)
        else:
            self.conn.execute(
                """INSERT INTO memories (owner_id, kind, content, tags, embedding, confidence)
                   VALUES (%s, 'semantic', %s, 'consolidated', %s::vector, 0.6)""",
                (owner_id, fact, vec),
            )

    # -- arbitrate (the palimpsest layering) -------------------------------

    def arbitrate(self, owner_id: str, old_id: str, old_content: str, new_fact: str) -> str:
        """Reconcile a conflict by writing a NEW layer over the old memory.

        The old memory is archived — still readable underneath, linked via
        ``supersedes`` — instead of being overwritten. Memory history stays
        auditable forever.
        """
        reconciled = self.llm.complete(
            ARBITRATE_PROMPT.format(old=old_content, new=new_fact), max_tokens=200
        ) or f"{old_content} (updated: {new_fact})"
        vec = to_vector_literal(self.embedder.embed(reconciled))
        row = self.conn.execute(
            """INSERT INTO memories
                   (owner_id, kind, content, tags, embedding, confidence, supersedes)
               VALUES (%s, 'semantic', %s, 'reconciled', %s::vector, 0.7, %s)
               RETURNING id""",
            (owner_id, reconciled, vec, old_id),
        ).fetchone()
        self.conn.execute(
            "UPDATE memories SET archived = true, updated_at = now() WHERE id = %s",
            (old_id,),
        )
        self._audit(
            owner_id, "arbitrate",
            {"superseded": old_id, "new_id": str(row[0])},
        )
        return str(row[0])

    def layers(self, memory_id: str) -> list[dict[str, Any]]:
        """Walk the supersedes chain: the memory and every layer beneath it."""
        out: list[dict[str, Any]] = []
        current: str | None = memory_id
        while current:
            row = self.conn.execute(
                """SELECT id, content, supersedes, archived, created_at
                   FROM memories WHERE id = %s""",
                (current,),
            ).fetchone()
            if row is None:
                break
            out.append(
                {"id": str(row[0]), "content": row[1], "archived": row[3],
                 "created_at": row[4].isoformat()}
            )
            current = str(row[2]) if row[2] else None
        return out

    # -- decay ------------------------------------------------------------

    def decay(self, owner_id: str | None = None) -> int:
        """Forgetting curve, set-based: heat decays everywhere; cold episodic
        memories leave the retrieval index (archived, never deleted)."""
        scope = "AND owner_id = %s" if owner_id else ""
        params: tuple = (settings.decay_factor,) + ((owner_id,) if owner_id else ())
        self.conn.execute(
            f"UPDATE memories SET heat = heat * %s WHERE archived = false {scope}",
            params,
        )
        params = (settings.archive_below,) + ((owner_id,) if owner_id else ())
        archived = self.conn.execute(
            f"""UPDATE memories SET archived = true, updated_at = now()
                WHERE archived = false AND kind = 'episodic' AND heat < %s {scope}
                RETURNING id""",
            params,
        ).fetchall()
        self._audit(owner_id or "*", "decay", {"archived": len(archived)})
        return len(archived)

    # -- audit ------------------------------------------------------------

    def _audit(self, owner_id: str, action: str, detail: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO audit_log (owner_id, action, detail) VALUES (%s, %s, %s)",
            (owner_id, action, json.dumps(detail)),
        )
