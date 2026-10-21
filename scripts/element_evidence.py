"""Do real meetings describe timers and sub-processes? (operator tool; no AI)

    uv run python scripts/element_evidence.py

Counts meetings across all real workspaces (demo sandboxes excluded) that mention waiting
periods, deadlines or reminders (BPMN timer events) or separate sub-processes, with a few
example lines. Rule of thumb: add an element to the extractor once ≥ 20% of at least 10 real
meetings describe it. Prints counts only by default; --examples shows meeting text, so only
use it where you're allowed to read customer content.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models import Organization, Transcript  # noqa: E402
from app.db.tenancy import system_session  # noqa: E402
from app.pipeline.signals import Evidence  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", action="store_true", help="print example lines (customer text)")
    args = ap.parse_args()
    ev = Evidence()
    with system_session() as db:
        real = select(Organization.id).where(Organization.sandbox_expires_at.is_(None))
        for t in db.scalars(
            select(Transcript).where(Transcript.purpose == "meeting", Transcript.organization_id.in_(real))
        ):
            if t.segments:
                ev.add([x["text"] for x in t.segments])
    n = ev.meetings or 1
    print(f"{ev.meetings} meetings")
    print(f"  timers (waits, deadlines, reminders): {ev.with_timers} ({ev.with_timers / n:.0%})")
    print(f"  sub-processes:                        {ev.with_subprocesses} ({ev.with_subprocesses / n:.0%})")
    enough = ev.meetings >= 10
    for label, k in (("timers", ev.with_timers), ("sub-processes", ev.with_subprocesses)):
        verdict = "add it" if enough and k / n >= 0.2 else "not yet" if enough else "need ≥ 10 real meetings first"
        print(f"  → {label}: {verdict}")
    if args.examples:
        print("\nTimer examples:", *ev.timer_examples, sep="\n  ")
        print("\nSub-process examples:", *ev.subprocess_examples, sep="\n  ")


if __name__ == "__main__":
    main()
