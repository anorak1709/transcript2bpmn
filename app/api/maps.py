from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import maps
from app.db.base import get_db
from app.db.models import ProcessMap, Transcript
from app.llm.provider import LiteLLMProvider, LLMProvider
from app.models.process import ProcessModel
from app.pipeline.edit import OpError, plan_edit
from app.pipeline.parse_bpmn import BpmnImportError, read_bpmn
from app.pipeline.validate import ValidationError, validate

router = APIRouter(prefix="/maps")

MAX_BPMN_BYTES = 5 * 1024 * 1024


def get_llm() -> LLMProvider:
    """Dependency so tests can swap in a fake."""
    return LiteLLMProvider()


DB = Annotated[Session, Depends(get_db)]
LLM = Annotated[LLMProvider, Depends(get_llm)]


class SegmentOut(BaseModel):
    segment_id: str
    speaker: str | None
    start_ts: float | None
    text: str


class MapOut(BaseModel):
    id: str
    transcript_id: str
    version: int
    can_undo: bool
    model: dict[str, Any]
    bpmn_xml: str
    errors: list[ValidationError]  # live validation of the current version
    segments: list[SegmentOut]  # transcript lines, so the editor can show a node's source quotes
    diarization_available: bool | None


class ChatIn(BaseModel):
    instruction: str


class ChatOut(MapOut):
    reply: str
    ops: list[dict[str, Any]]


class VersionOut(BaseModel):
    version: int
    source: str
    instruction: str | None
    created_at: datetime


def _load(db: Session, map_id: str) -> ProcessMap:
    pmap = db.get(ProcessMap, map_id)
    if pmap is None:
        raise HTTPException(404, "Map not found")
    return pmap


def _out(db: Session, pmap: ProcessMap) -> MapOut:
    transcript = db.get_one(Transcript, pmap.transcript_id)
    return MapOut(
        id=pmap.id,
        transcript_id=pmap.transcript_id,
        version=pmap.current_version,
        can_undo=pmap.current_version > 1,
        model=pmap.model,
        bpmn_xml=pmap.bpmn_xml,
        errors=validate(ProcessModel.model_validate(pmap.model)),
        segments=[SegmentOut.model_validate(s) for s in transcript.segments or []],
        diarization_available=transcript.diarization_available,
    )


@router.get("/{map_id}")
def get_map(map_id: str, db: DB) -> MapOut:
    return _out(db, _load(db, map_id))


@router.post("/{map_id}/chat")
def chat_edit(map_id: str, body: ChatIn, db: DB, llm: LLM) -> ChatOut:
    """Instruction -> LLM patch ops -> applied deterministically -> new version."""
    pmap = _load(db, map_id)
    current = ProcessModel.model_validate(pmap.model)
    try:
        model, plan = plan_edit(llm, current, body.instruction)
    except OpError as e:
        raise HTTPException(422, f"Couldn't apply that edit: {e}") from e
    ops = [op.model_dump() for op in plan.ops]
    if ops:  # a clarifying question changes nothing and creates no version
        maps.commit_version(db, pmap, model, "chat", maps.current_positions(pmap), ops, body.instruction)
        db.commit()
    return ChatOut(**_out(db, pmap).model_dump(), reply=plan.reply, ops=ops)


@router.post("/{map_id}/undo")
def undo(map_id: str, db: DB) -> MapOut:
    pmap = _load(db, map_id)
    try:
        maps.undo(db, pmap)
    except maps.NothingToUndo:
        raise HTTPException(409, "Nothing to undo") from None
    db.commit()
    return _out(db, pmap)


@router.put("/{map_id}/bpmn")
def save_bpmn(map_id: str, db: DB, xml: Annotated[bytes, Body(media_type="application/xml")]) -> MapOut:
    """Visual edit: BPMN XML from the editor -> ProcessModel (matched by id) -> new version.
    The editor's node positions are kept; the stored XML is regenerated from the model."""
    if len(xml) > MAX_BPMN_BYTES:
        raise HTTPException(413, "BPMN document too large")
    pmap = _load(db, map_id)
    try:
        model, positions = read_bpmn(xml, ProcessModel.model_validate(pmap.model))
    except BpmnImportError as e:
        raise HTTPException(422, str(e)) from e
    maps.commit_version(db, pmap, model, "visual", positions)
    db.commit()
    return _out(db, pmap)


@router.get("/{map_id}/versions")
def list_versions(map_id: str, db: DB) -> list[VersionOut]:
    _load(db, map_id)
    return [VersionOut.model_validate(v, from_attributes=True) for v in maps.versions(db, map_id)]
