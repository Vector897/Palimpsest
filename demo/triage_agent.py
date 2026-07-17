"""Demo agent: a morning news-briefing agent with Palimpsest memory.

It triages tech-news headlines for one reader, learning what they care about.

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

OWNER = "demo-news"

# Neutral tech-news headlines. The reader (revealed through feedback) follows
# database and developer-tooling news and ignores roundups, listicles, and
# off-topic consumer stories.
PAPERS = {
    1: [
        ("Postgres 18 ships asynchronous I/O for sequential scans",
         "The release adds async I/O, cutting latency on large analytical table scans."),
        ("The 25 best productivity apps of the year",
         "A ranked roundup of note-taking, calendar, and to-do apps across platforms."),
        ("Streaming service raises monthly subscription prices again",
         "The consumer platform announced a price hike alongside a new ad-supported tier."),
        ("Rust 1.85 stabilizes async functions in traits",
         "Long-awaited async-fn-in-trait support lands, simplifying async library design."),
        ("Titanium smartwatch unveiled with a three-day battery",
         "A hardware maker showed its new flagship wearable at an autumn launch event."),
        ("A roundup of every cloud announcement this month",
         "A monthly digest summarizing dozens of vendor announcements in a single post."),
    ],
    2: [
        ("SQLite adds a built-in vector search extension",
         "The embedded database gains native approximate nearest-neighbor search."),
        ("The top 15 cloud trends to watch this year",
         "An analyst roundup forecasting the year's dominant cloud themes."),
        ("Go 1.24 introduces generic type aliases",
         "The release lets developers alias generic types, cutting boilerplate."),
        ("Celebrity launches a new weekly podcast network",
         "An entertainment figure announced a slate of shows and a hosting deal."),
        ("Best noise-cancelling headphones, ranked for the season",
         "A consumer buying guide rating the latest over-ear headphones."),
        ("A survey of frontend framework popularity",
         "A broad survey aggregating developer-poll data across web frameworks."),
    ],
}

TRIAGE_PROMPT = """\
You triage tech-news stories for one specific reader.

What you remember about this reader (from long-term memory, may be empty):
{memories}

Story: {title}
Summary: {abstract}

Match at the level of TOPIC or DOMAIN, not exact products: a remembered interest
in database performance covers any database-internals story (including a new
database feature); an interest in one programming language or developer tool
covers other language and tooling stories. If any remembered interest matches
the story's domain, answer IMPORTANT. If it matches something the reader ignores
(roundups, listicles, surveys, off-topic consumer news), answer SKIP. With no
memories, judge by general newsworthiness.
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
        f"Reader marked the story '{title}' as {verdict}. (Summary: {abstract[:120]})",
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
