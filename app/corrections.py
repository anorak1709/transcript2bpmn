"""The corrections flywheel: every human edit to an AI-drafted map is a free label showing where
the extraction was wrong. Recorded per workspace; turned into test cases only with consent.

Sharing (Organization.share_corrections):
- off: recorded and visible to the workspace, never exported for training/evaluation.
- anonymised: exportable without meeting text, and with speakers replaced by "Speaker 1…".
- full: exportable with the transcript text, so each case can be re-run as a regression test.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Correction, Organization, ProcessMap, Project, Transcript
from app.models.process import ProcessModel

HUMAN_SOURCES = ("visual", "chat")  # merges, settled points and undo aren't corrections
SHARING = ("off", "anonymised", "full")


def diff(old: ProcessModel, new: ProcessModel) -> list[dict[str, Any]]:
    """What a person changed in what the AI had extracted. Changes to steps a person added
    themselves aren't the AI's errors, so they're skipped."""
    lanes_old = {x.id: x.name for x in old.lanes}
    lanes_new = {x.id: x.name for x in new.lanes}
    before = {n.id: n for n in old.nodes}
    after = {n.id: n for n in new.nodes}
    out: list[dict[str, Any]] = []

    def add(kind: str, node_id: str | None, b: Any, a: Any, evidence: list[str] | None = None) -> None:
        out.append({"kind": kind, "node_id": node_id, "before": b, "after": a, "segment_ids": evidence or []})

    def lane(lanes: dict[str, str], lane_id: str) -> str:
        return lanes.get(lane_id, lane_id)

    for nid, o in before.items():
        if o.user_added:
            continue
        n, ev = after.get(nid), list(o.source_segment_ids)
        if n is None:
            add("delete", nid, {"name": o.name, "type": o.type, "lane": lane(lanes_old, o.lane_id)}, None, ev)
            continue
        if n.name != o.name:
            add("rename", nid, {"name": o.name}, {"name": n.name}, ev)
        if lane(lanes_new, n.lane_id) != lane(lanes_old, o.lane_id):
            b = {"name": o.name, "lane": lane(lanes_old, o.lane_id)}
            add("move", nid, b, {"name": n.name, "lane": lane(lanes_new, n.lane_id)}, ev)
        if n.type != o.type:
            add("retype", nid, {"name": o.name, "type": o.type}, {"name": n.name, "type": n.type}, ev)
    for nid, n in after.items():
        if nid not in before:  # something the AI missed
            add("add", nid, None, {"name": n.name, "type": n.type, "lane": lane(lanes_new, n.lane_id)})

    names_old = {n.id: n.name for n in old.nodes}
    names_new = {n.id: n.name for n in new.nodes}
    e_old = {(f.source_id, f.target_id) for f in old.flows if f.source_id in before and f.target_id in before}
    e_new = {(f.source_id, f.target_id) for f in new.flows if f.source_id in after and f.target_id in after}
    for s, t in sorted(e_old - e_new):
        if s in after and t in after:  # a deleted step's flows are part of the delete
            add("disconnect", None, {"from": names_old[s], "to": names_old[t]}, None)
    for s, t in sorted(e_new - e_old):
        if s in before and t in before:  # flows to a new step are part of the add
            add("connect", None, None, {"from": names_new[s], "to": names_new[t]})
    return out


def record(db: Session, pmap: ProcessMap, old: ProcessModel, new: ProcessModel, via: str, version: int) -> int:
    """Store the corrections one human edit made (called from maps.commit_version)."""
    rows = diff(old, new)
    for r in rows:
        db.add(Correction(project_id=pmap.project_id, map_id=pmap.id, version=version, via=via, **r))
    return len(rows)


def export_cases(db: Session, org: Organization) -> list[dict[str, Any]]:
    """The workspace's corrections as evaluation cases, at the level it consented to. One case per
    meeting map that was corrected: the AI's version, what people changed, and (full sharing
    only) the transcript, so eval/corrections_eval.py can re-run extraction on it."""
    if org.share_corrections not in ("anonymised", "full"):
        return []
    full = org.share_corrections == "full"
    cases: dict[str, dict[str, Any]] = {}
    for c in db.scalars(select(Correction).order_by(Correction.created_at)):
        pmap = db.get(ProcessMap, c.map_id)
        if pmap is None:
            continue
        case = cases.setdefault(
            c.map_id,
            {"case": c.map_id[:8], "process": db.get_one(Project, c.project_id).name if full else None,
             "meetings": _meetings(db, pmap) if full else None, "corrections": []},
        )  # fmt: skip
        case["corrections"].append(
            {"kind": c.kind, "before": c.before, "after": c.after, "via": c.via}
            | ({"segment_ids": c.segment_ids} if full else {})
        )
    return [c for c in cases.values() if c["corrections"]]


def _meetings(db: Session, pmap: ProcessMap) -> list[list[dict[str, Any]]]:
    """The meeting text behind a map, one list of lines per meeting, in upload order: the single
    meeting for a meeting's own map, every meeting for a merged map (what extraction + merge saw)."""
    if pmap.transcript_id is not None:
        ts = [db.get_one(Transcript, pmap.transcript_id)]
    else:
        ts = list(
            db.scalars(
                select(Transcript)
                .where(Transcript.project_id == pmap.project_id, Transcript.purpose == "meeting")
                .order_by(Transcript.created_at)
            )
        )
    return [[{"speaker": x.get("speaker"), "text": x["text"]} for x in (t.segments or [])] for t in ts if t.segments]
