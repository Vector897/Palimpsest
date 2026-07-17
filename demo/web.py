"""Palimpsest demo web panel.

    pip install -e ".[demo]"
    python demo/web.py            # http://localhost:8777

One page, four acts: run the morning triage (with or without memory), give
feedback, run nightly consolidation (the Lambda code path), and crash/recover
mid-run. The memory pane shows semantic facts with their palimpsest layers.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from palimpsest.adapters.lambda_consolidate import handler as nightly  # noqa: E402
from palimpsest.db import apply_schema, connect  # noqa: E402
from palimpsest.engine import checkpoints  # noqa: E402
from palimpsest.engine.memory import MemoryEngine  # noqa: E402

from triage_agent import OWNER, PAPERS, triage_paper  # noqa: E402

app = FastAPI(title="Palimpsest demo")
STATIC = Path(__file__).parent / "static"

_eng: MemoryEngine | None = None


def eng() -> MemoryEngine:
    global _eng
    if _eng is None:
        conn = connect()
        apply_schema(conn)
        _eng = MemoryEngine(conn)
    return _eng


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def state() -> JSONResponse:
    e = eng()
    semantic = e.conn.execute(
        """SELECT id, content, confidence, heat, tags, supersedes IS NOT NULL
           FROM memories WHERE owner_id=%s AND kind='semantic' AND archived=false
           ORDER BY created_at DESC LIMIT 20""",
        (OWNER,),
    ).fetchall()
    episodic = e.conn.execute(
        """SELECT content, created_at FROM memories
           WHERE owner_id=%s AND kind='episodic' AND archived=false
           ORDER BY created_at DESC LIMIT 8""",
        (OWNER,),
    ).fetchall()
    audit = e.conn.execute(
        """SELECT action, detail, created_at FROM audit_log
           WHERE owner_id=%s ORDER BY created_at DESC LIMIT 10""",
        (OWNER,),
    ).fetchall()
    days = {}
    for day in (1, 2):
        cp = checkpoints.load_latest(e.conn, OWNER, f"triage-day{day}")
        days[day] = cp[1] if cp else None
    return JSONResponse({
        "papers": {d: [{"title": t, "abstract": a} for t, a in ps] for d, ps in PAPERS.items()},
        "days": days,
        "semantic": [
            {"id": str(r[0]), "content": r[1], "confidence": r[2], "heat": round(r[3], 2),
             "tags": r[4], "reconciled": r[5]} for r in semantic
        ],
        "episodic": [{"content": r[0], "at": r[1].isoformat()} for r in episodic],
        "audit": [{"action": r[0], "detail": r[1], "at": r[2].isoformat()} for r in audit],
    })


class MorningReq(BaseModel):
    day: int = 1
    crash_after: int | None = None


@app.post("/api/morning")
def morning(req: MorningReq) -> JSONResponse:
    e = eng()
    task_id = f"triage-day{req.day}"
    papers = PAPERS[req.day]

    start, decisions, recovered = 0, [], False
    if cp := checkpoints.load_latest(e.conn, OWNER, task_id):
        _, st = cp
        if st["next"] < len(papers):
            start, decisions, recovered = st["next"], st["decisions"], True
        # else: fully triaged before — start fresh

    for i in range(start, len(papers)):
        title, abstract = papers[i]
        result = triage_paper(e, title, abstract)
        decisions.append({"paper": i + 1, "title": title, **result})
        checkpoints.save(e.conn, OWNER, task_id, f"paper-{i + 1}",
                         {"next": i + 1, "decisions": decisions})
        if req.crash_after is not None and i + 1 >= req.crash_after:
            return JSONResponse({"crashed": True, "at": i + 1, "decisions": decisions})

    return JSONResponse({"crashed": False, "recovered": recovered,
                         "resumed_at": start + 1 if recovered else None,
                         "decisions": decisions})


class FeedbackReq(BaseModel):
    day: int
    paper: int
    verdict: str  # important | ignore


@app.post("/api/feedback")
def feedback(req: FeedbackReq) -> JSONResponse:
    e = eng()
    title, abstract = PAPERS[req.day][req.paper - 1]
    e.write_episodic(
        OWNER,
        f"User marked the paper '{title}' as {req.verdict}. (Abstract: {abstract[:120]})",
        tags=f"feedback,{req.verdict}",
    )
    return JSONResponse({"ok": True})


@app.post("/api/night")
def night() -> JSONResponse:
    return JSONResponse(nightly())


@app.get("/api/layers/{memory_id}")
def layers(memory_id: str) -> JSONResponse:
    return JSONResponse(eng().layers(memory_id))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8777)
