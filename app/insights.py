"""Who said what: speakers and their roles, and the quotes behind each side of a disagreement.

Free (no LLM): everything comes from stored transcript segments and the user's role tags.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conflict, Project, Transcript

ROLES = ("owner", "performer", "observer")
ROLE_LABEL = {"owner": "process owner", "performer": "does the work", "observer": "observer"}


@dataclass
class Quote:
    text: str | None  # None: deleted by retention
    speaker: str | None
    role: str | None  # owner | performer | observer | None (untagged)
    meeting: str  # filename
    start_ts: float | None
    policy: bool = False  # from a policy document, not a meeting


@dataclass
class Side:
    label: str  # the option this side argues for, or which meetings it is
    quotes: list[Quote] = field(default_factory=list)


def segment_index(db: Session, project_id: str) -> dict[str, Quote]:
    """Every line of the project's files by qualified id (`<transcript_id>:<segment_id>`), as
    merged maps and conflicts cite them."""
    roles = db.get_one(Project, project_id).speaker_roles or {}
    out: dict[str, Quote] = {}
    for t in db.scalars(select(Transcript).where(Transcript.project_id == project_id)):
        for s in t.segments or []:
            out[f"{t.id}:{s['segment_id']}"] = Quote(
                text=s["text"],
                speaker=s.get("speaker"),
                role=roles.get(s.get("speaker") or ""),
                meeting=t.filename,
                start_ts=s.get("start_ts"),
                policy=t.purpose == "policy",
            )
    return out


def speakers(db: Session, project: Project) -> list[dict[str, object]]:
    """People heard in the project's meetings (policy documents have no speakers), with their
    role tag and how much they said."""
    lines: dict[str, int] = {}
    meetings: dict[str, set[str]] = {}
    for t in db.scalars(select(Transcript).where(Transcript.project_id == project.id, Transcript.purpose == "meeting")):
        for s in t.segments or []:
            who = (s.get("speaker") or "").strip()
            if who and who.lower() != "unknown speaker":
                lines[who] = lines.get(who, 0) + 1
                meetings.setdefault(who, set()).add(t.id)
    roles = project.speaker_roles or {}
    return [
        {"name": n, "role": roles.get(n), "lines": lines[n], "meetings": len(meetings[n])}
        for n in sorted(lines, key=lambda n: (-lines[n], n))
    ]


def sides(c: Conflict, index: dict[str, Quote]) -> list[Side]:
    """The quotes behind each side. For owner/condition/order the two sides are the two
    options; a sequence question has more options than sides, so sides are named by source."""
    aligned = len(c.sources) == len(c.options)
    out = []
    for i, src in enumerate(c.sources):
        if aligned:
            label = c.options[i]
        elif c.origin == "policy":
            label = "The meetings" if i == 0 else "The policy"
        else:
            label = "Earlier meetings" if i == 0 else "The latest meeting"
        quotes = [index.get(sid) or Quote(None, None, None, "", None) for sid in src.get("segment_ids", [])]
        out.append(Side(label, [q for q in quotes if q.meeting]))
    return out


def owner_side(ss: list[Side]) -> int | None:
    """The side the process owner backs, when exactly one side has a process owner on it.
    Shown, not acted on: the user still decides."""
    backed = [i for i, s in enumerate(ss) if any(q.role == "owner" for q in s.quotes)]
    return backed[0] if len(backed) == 1 else None


def people(quotes: list[Quote]) -> list[str]:
    """Distinct speakers, in order, as "Name (role)"."""
    seen: dict[str, str | None] = {}
    for q in quotes:
        if q.speaker and not q.policy and q.speaker.lower() != "unknown speaker":
            seen.setdefault(q.speaker, q.role)
    return [f"{n} ({ROLE_LABEL[r]})" if r else n for n, r in seen.items()]
