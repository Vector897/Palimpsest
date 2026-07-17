"""Demo agent: a morning paper-triage assistant with Palimpsest memory.

A day in the life:

    python demo/triage_agent.py morning --day 1     # no memory yet: generic triage
    python demo/triage_agent.py feedback --day 1 --paper 1 --verdict important
    python demo/triage_agent.py feedback --day 1 --paper 4 --verdict important
    python demo/triage_agent.py feedback --day 1 --paper 2 --verdict ignore
    python demo/triage_agent.py night               # consolidation (same code as the Lambda)
    python demo/triage_agent.py morning --day 2     # memory-informed decisions

The money shot — kill the agent mid-run, memory and progress survive in CockroachDB:

    python demo/triage_agent.py morning --day 2 --crash-after 2   # simulated crash
    python demo/triage_agent.py morning --day 2                   # resumes from checkpoint
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.adapters.lambda_consolidate import handler as nightly  # noqa: E402
from palimpsest.db import apply_schema, connect  # noqa: E402
from palimpsest.engine import checkpoints  # noqa: E402
from palimpsest.engine.memory import MemoryEngine  # noqa: E402

OWNER = "demo-triage"

PAPERS = {
    1: [
        ("[redacted title]",
         "[redacted summary]"),
        ("[redacted title]",
         "[redacted summary]"),
        ("Diffusion Models for Protein Folding",
         "We apply score-based diffusion to protein structure prediction."),
        ("[redacted title]",
         "[redacted summary]"),
        ("Quantum Error Correction with Neural Decoders",
         "Neural network decoders for surface codes at scale."),
        ("Prompt Engineering Best Practices: an Empirical Study",
         "A survey of prompting techniques across 12 LLM families."),
    ],
    2: [
        ("[redacted title]",
         "[redacted summary]"),
        ("A Survey of Vision Transformers in Medical Imaging",
         "Comprehensive survey of ViT applications to radiology."),
        ("[redacted title]",
         "[redacted summary]"),
        ("Text-to-Music Generation at Scale",
         "Scaling laws for music generation models."),
        ("[redacted title]",
         "[redacted summary]"),
        ("An Empirical Survey of Data Augmentation",
         "A survey of augmentation strategies across modalities."),
    ],
}

TRIAGE_PROMPT = """\
You triage research papers for one specific user.

What you remember about this user (from long-term memory, may be empty):
{memories}

Paper: {title}
Abstract: {abstract}

Decide for THIS user: if any remembered interest plausibly matches the paper's
topic, prefer IMPORTANT; if the paper matches something the user ignores,
prefer SKIP. With no memories, judge by general novelty.
Reply in exactly this format (two lines):
VERDICT: IMPORTANT or SKIP
REASON: one short sentence"""


def _engine() -> MemoryEngine:
    conn = connect()
    apply_schema(conn)
    return MemoryEngine(conn)


def triage_paper(eng: MemoryEngine, title: str, abstract: str) -> dict:
    """Triage one paper against the agent's semantic memory. Shared by CLI and web demo."""
    hits = eng.retrieve(OWNER, f"{title}. {abstract}", limit=3, kinds=("semantic",))
    memory_text = "\n".join(f"- {m.content}" for m in hits) or "(no long-term memories yet)"
    raw = eng.llm.complete(
        TRIAGE_PROMPT.format(memories=memory_text, title=title, abstract=abstract),
        max_tokens=100,
    )
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    verdict = "IMPORTANT" if lines and "IMPORTANT" in lines[0].upper() else "SKIP"
    reason = ""
    for ln in lines[1:]:
        if ln.upper().startswith("REASON"):
            reason = ln.split(":", 1)[-1].strip()
            break
    return {
        "verdict": verdict,
        "reason": reason,
        "memories_used": [m.content for m in hits],
    }


def morning(day: int, crash_after: int | None) -> None:
    eng = _engine()
    task_id = f"triage-day{day}"
    papers = PAPERS[day]

    start, decisions = 0, []
    if cp := checkpoints.load_latest(eng.conn, OWNER, task_id):
        _, state = cp
        start, decisions = state["next"], state["decisions"]
        if start >= len(papers):
            print(f"(day {day} already fully triaged — clearing old checkpoint and starting fresh)")
            start, decisions = 0, []
        else:
            print(f"*** RECOVERED FROM CHECKPOINT: resuming at paper {start + 1}, "
                  f"{len(decisions)} decisions already made (no tokens re-spent) ***")

    for i in range(start, len(papers)):
        title, abstract = papers[i]
        result = triage_paper(eng, title, abstract)
        verdict, reason = result["verdict"], result["reason"]
        decisions.append({"paper": i + 1, "title": title, "verdict": verdict})
        flag = "★ IMPORTANT" if verdict == "IMPORTANT" else "  skip     "
        print(f"{flag}  {i + 1}. {title}\n             {reason}")

        checkpoints.save(eng.conn, OWNER, task_id, f"paper-{i + 1}",
                         {"next": i + 1, "decisions": decisions})
        if crash_after is not None and i + 1 >= crash_after:
            print(f"\n*** SIMULATED CRASH after paper {i + 1} (kill -9) — "
                  f"memory and progress are safe in CockroachDB ***")
            sys.exit(1)

    important = sum(1 for d in decisions if d["verdict"] == "IMPORTANT")
    print(f"\nMorning briefing done: {important} important / {len(papers)} papers.")
    eng.conn.close()


def feedback(day: int, paper: int, verdict: str) -> None:
    eng = _engine()
    title, abstract = PAPERS[day][paper - 1]
    eng.write_episodic(
        OWNER,
        f"User marked the paper '{title}' as {verdict}. (Abstract: {abstract[:120]})",
        tags=f"feedback,{verdict}",
    )
    print(f"recorded: paper {paper} -> {verdict}")
    eng.conn.close()


def night() -> None:
    print("running nightly consolidation (identical code path to the AWS Lambda)...")
    print(nightly())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("morning")
    m.add_argument("--day", type=int, default=1, choices=(1, 2))
    m.add_argument("--crash-after", type=int, default=None)
    f = sub.add_parser("feedback")
    f.add_argument("--day", type=int, default=1, choices=(1, 2))
    f.add_argument("--paper", type=int, required=True)
    f.add_argument("--verdict", choices=("important", "ignore"), required=True)
    sub.add_parser("night")
    args = p.parse_args()

    if args.cmd == "morning":
        morning(args.day, args.crash_after)
    elif args.cmd == "feedback":
        feedback(args.day, args.paper, args.verdict)
    else:
        night()


if __name__ == "__main__":
    main()
