"""Stakeholder sign-off: a private review link per person, showing only their part of the map.

Owner side (API key): create, list and revoke links. Reviewer side (the link's token, no
account): read their steps and approve or request changes. Each decision records the map
version the reviewer saw, so approvals are audit evidence.
"""

import hashlib
import hmac
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import insights
from app.api.projects import QuoteOut, _project
from app.audit import audit
from app.auth import DB
from app.db.models import ProcessMap, Project, Signoff
from app.db.tenancy import bind, system_session
from app.models.process import TASK_TYPES, ProcessModel
from app.ratelimit import rate_limit

router = APIRouter(dependencies=[Depends(rate_limit("api"))])
# ponytail: no rate limit on the public side; tokens are 192-bit random, so guessing is moot.
# Add a per-IP limit if the review endpoints ever get abused.
public = APIRouter()

LINK_DAYS = 30


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SignoffIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    lane_ids: list[str] = Field(min_length=1)


class SignoffOut(BaseModel):
    id: str
    name: str
    lanes: list[str]  # lane names, for display
    lane_ids: list[str]
    status: str  # pending | approved | changes_requested | revoked | expired
    comment: str | None
    requested_version: int
    decided_version: int | None
    current_version: int | None  # if newer than decided_version, the approval predates edits
    created_at: datetime | None
    decided_at: datetime | None
    expires_at: datetime
    token: str | None = None  # only in the create response: the link is shown once


def _status(s: Signoff) -> str:
    if s.revoked_at:
        return "revoked"
    if s.decision:
        return s.decision
    expires = s.expires_at if s.expires_at.tzinfo else s.expires_at.replace(tzinfo=UTC)
    return "expired" if expires < datetime.now(UTC) else "pending"


def _out(db: Session, s: Signoff, project: Project) -> SignoffOut:
    pmap = db.get(ProcessMap, project.merged_map_id) if project.merged_map_id else None
    lanes = {x["id"]: x["name"] for x in pmap.model["lanes"]} if pmap else {}
    return SignoffOut(
        id=s.id,
        name=s.name,
        lanes=[lanes.get(lid, lid) for lid in s.lane_ids],
        lane_ids=s.lane_ids,
        status=_status(s),
        comment=s.comment,
        requested_version=s.requested_version,
        decided_version=s.decided_version,
        current_version=pmap.current_version if pmap else None,
        created_at=s.created_at,
        decided_at=s.decided_at,
        expires_at=s.expires_at,
    )


@router.post("/projects/{project_id}/signoffs", status_code=201)
def request_signoff(project_id: str, body: SignoffIn, db: DB) -> SignoffOut:
    p = _project(db, project_id)
    if not p.merged_map_id:
        raise HTTPException(409, "There's no map to sign off yet: process a meeting first")
    pmap = db.get_one(ProcessMap, p.merged_map_id)
    known = {x["id"] for x in pmap.model["lanes"]}
    if not set(body.lane_ids) <= known:
        raise HTTPException(400, "Choose lanes from this process's map")
    token = "rv_" + secrets.token_urlsafe(24)
    s = Signoff(
        project_id=p.id,
        name=body.name.strip(),
        lane_ids=list(dict.fromkeys(body.lane_ids)),
        token_hash=_hash(token),
        requested_version=pmap.current_version,
        expires_at=datetime.now(UTC) + timedelta(days=LINK_DAYS),
    )
    db.add(s)
    db.flush()
    audit(db, "request_signoff", "signoff", s.id, project_id=p.id, lanes=len(s.lane_ids))
    db.commit()
    db.refresh(s)
    return _out(db, s, p).model_copy(update={"token": token})


@router.get("/projects/{project_id}/signoffs")
def list_signoffs(project_id: str, db: DB) -> list[SignoffOut]:
    p = _project(db, project_id)
    rows = db.scalars(select(Signoff).where(Signoff.project_id == p.id).order_by(Signoff.created_at))
    return [_out(db, s, p) for s in rows]


@router.delete("/signoffs/{signoff_id}")
def revoke_signoff(signoff_id: str, db: DB) -> SignoffOut:
    s = db.get(Signoff, signoff_id)
    if s is None:
        raise HTTPException(404, "Sign-off not found")
    if not s.revoked_at:
        s.revoked_at = datetime.now(UTC)
        audit(db, "revoke_signoff", "signoff", s.id, project_id=s.project_id)
        db.commit()
    return _out(db, s, _project(db, s.project_id))


# --- Reviewer side: the token is the credential ---------------------------------------------


def _review_db(token: str) -> Iterator[tuple[Session, Signoff]]:
    with system_session() as lookup:
        row = lookup.scalars(select(Signoff).where(Signoff.token_hash == _hash(token))).first()
        found = (row.id, row.organization_id) if row and hmac.compare_digest(row.token_hash, _hash(token)) else None
    if found is None:
        raise HTTPException(404, "This review link isn't valid")
    with system_session() as db:
        bind(db, found[1])  # from here on, scoped to the link's organization like any request
        s = db.get_one(Signoff, found[0])
        if _status(s) in ("revoked", "expired"):
            raise HTTPException(410, f"This review link has {_status(s).replace('revoked', 'been withdrawn')}")
        yield db, s


Review = Annotated[tuple[Session, Signoff], Depends(_review_db)]


class Neighbour(BaseModel):
    name: str
    lane: str
    condition: str | None


class StepOut(BaseModel):
    id: str
    kind: str  # task | decision
    name: str
    lane: str
    comes_from: list[Neighbour]
    goes_to: list[Neighbour]
    quotes: list[QuoteOut]


class ReviewOut(BaseModel):
    process: str
    name: str
    lanes: list[str]
    version: int
    requested_version: int
    steps: list[StepOut]
    decision: str | None
    comment: str | None
    decided_version: int | None
    decided_at: datetime | None
    expires_at: datetime


class DecisionIn(BaseModel):
    decision: Literal["approved", "changes_requested"]
    comment: str | None = Field(default=None, max_length=4000)


def _steps(model: ProcessModel, lane_ids: list[str], index: dict[str, insights.Quote]) -> list[StepOut]:
    """Only the reviewer's part: their tasks and decisions, each with where it comes from and
    goes to (looking through unnamed join/split points), and the quotes behind it."""
    lanes = {x.id: x.name for x in model.lanes}
    nodes = {n.id: n for n in model.nodes}
    flows = model.flows

    def walk(nid: str, forward: bool, cond: str | None = None, seen: frozenset[str] = frozenset()) -> list[Neighbour]:
        out: list[Neighbour] = []
        for f in flows:
            src, dst = (f.source_id, f.target_id) if forward else (f.target_id, f.source_id)
            if src != nid or dst in seen or dst not in nodes:
                continue
            n = nodes[dst]
            c = (f.condition or cond) if forward else None
            if not n.name and n.type not in TASK_TYPES:  # unnamed gateway: look through it
                out += walk(n.id, forward, c, seen | {nid})
            else:
                out.append(Neighbour(name=n.name, lane=lanes.get(n.lane_id, ""), condition=c))
        return out

    steps = []
    for n in model.nodes:
        if n.lane_id not in lane_ids or not (n.type in TASK_TYPES or (n.type == "exclusive_gateway" and n.name)):
            continue
        quotes = [index[s] for s in n.source_segment_ids if s in index]
        steps.append(
            StepOut(
                id=n.id,
                kind="task" if n.type in TASK_TYPES else "decision",
                name=n.name,
                lane=lanes.get(n.lane_id, ""),
                comes_from=walk(n.id, forward=False),
                goes_to=walk(n.id, forward=True),
                quotes=[QuoteOut(**q.__dict__) for q in quotes],
            )
        )
    return steps


def _review(db: Session, s: Signoff) -> ReviewOut:
    project = db.get_one(Project, s.project_id)
    pmap = db.get_one(ProcessMap, project.merged_map_id)
    model = ProcessModel.model_validate(pmap.model)
    lanes = {x.id: x.name for x in model.lanes}
    return ReviewOut(
        process=project.name,
        name=s.name,
        lanes=[lanes.get(lid, lid) for lid in s.lane_ids],
        version=pmap.current_version,
        requested_version=s.requested_version,
        steps=_steps(model, s.lane_ids, insights.segment_index(db, project.id)),
        decision=s.decision,
        comment=s.comment,
        decided_version=s.decided_version,
        decided_at=s.decided_at,
        expires_at=s.expires_at,
    )


@public.get("/review/{token}")
def read_review(review: Review) -> ReviewOut:
    return _review(*review)


@public.post("/review/{token}")
def decide(body: DecisionIn, review: Review) -> ReviewOut:
    db, s = review
    project = db.get_one(Project, s.project_id)
    s.decision, s.comment = body.decision, (body.comment or "").strip() or None
    s.decided_version = db.get_one(ProcessMap, project.merged_map_id).current_version
    s.decided_at = datetime.now(UTC)
    audit(db, "signoff", "signoff", s.id, project_id=s.project_id, decision=body.decision, version=s.decided_version)
    db.commit()
    return _review(db, s)
