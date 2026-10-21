"""Workspace-level settings and data: corrections (the flywheel), sharing consent."""

from collections import Counter
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.audit import audit
from app.auth import DB, CurrentPrincipal
from app.db.models import Correction, Organization, Transcript
from app.pipeline.signals import Evidence
from app.ratelimit import rate_limit

router = APIRouter(dependencies=[Depends(rate_limit("api"))])


class WorkspaceOut(BaseModel):
    id: str
    name: str
    share_corrections: str  # off | anonymised | full
    sandbox_expires_at: datetime | None


class WorkspaceIn(BaseModel):
    share_corrections: Literal["off", "anonymised", "full"]


@router.get("/workspace")
def get_workspace(db: DB, who: CurrentPrincipal) -> WorkspaceOut:
    return WorkspaceOut.model_validate(db.get_one(Organization, who.org_id), from_attributes=True)


@router.put("/workspace")
def update_workspace(body: WorkspaceIn, db: DB, who: CurrentPrincipal) -> WorkspaceOut:
    org = db.get_one(Organization, who.org_id)
    org.share_corrections = body.share_corrections
    audit(db, "share_corrections", "organization", org.id, level=body.share_corrections)
    db.commit()
    return WorkspaceOut.model_validate(org, from_attributes=True)


class CorrectionOut(BaseModel):
    id: str
    project_id: str
    map_id: str
    version: int
    via: str
    kind: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime


class CorrectionsOut(BaseModel):
    total: int
    by_kind: dict[str, int]
    recent: list[CorrectionOut]


@router.get("/corrections")
def list_corrections(db: DB, limit: int = 50) -> CorrectionsOut:
    """Where people corrected the AI in this workspace: counts by kind, and the latest fixes."""
    rows = db.scalars(select(Correction).order_by(Correction.created_at.desc())).all()
    return CorrectionsOut(
        total=len(rows),
        by_kind=dict(Counter(r.kind for r in rows)),
        recent=[CorrectionOut.model_validate(r, from_attributes=True) for r in rows[: min(limit, 500)]],
    )


class ElementEvidenceOut(BaseModel):
    meetings: int
    with_timers: int
    with_subprocesses: int
    timer_examples: list[str]
    subprocess_examples: list[str]


@router.get("/insights/bpmn-elements")
def element_evidence(db: DB) -> ElementEvidenceOut:
    """How often this workspace's meetings describe waits/deadlines (timer events) and separate
    sub-processes: the evidence for whether the extractor should learn those elements."""
    ev = Evidence()
    for t in db.scalars(select(Transcript).where(Transcript.purpose == "meeting")):
        if t.segments:
            ev.add([x["text"] for x in t.segments])
    return ElementEvidenceOut(**ev.__dict__)


class IntegrationsOut(BaseModel):
    camunda: bool  # "Send to Camunda" is offered
    ai: bool  # AI features available (off in demo mode and sandboxes)


@router.get("/integrations")
def integrations(db: DB, who: CurrentPrincipal) -> IntegrationsOut:
    from app.demo import ai_allowed
    from app.integrations import camunda

    return IntegrationsOut(camunda=camunda.configured(), ai=ai_allowed(db.get(Organization, who.org_id)))
