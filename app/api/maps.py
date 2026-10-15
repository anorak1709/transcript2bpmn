import re
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import maps
from app.audit import audit
from app.auth import DB, CurrentPrincipal
from app.db.models import Conflict, ProcessMap, Transcript
from app.llm.provider import LiteLLMProvider, LLMProvider
from app.metrics import EXPORTS
from app.models.process import ProcessModel
from app.pipeline.edit import OpError, plan_edit
from app.pipeline.export import ExportError, render_image, sop_markdown
from app.pipeline.parse_bpmn import BpmnImportError, read_bpmn
from app.pipeline.validate import ValidationError, validate
from app.ratelimit import rate_limit

router = APIRouter(prefix="/maps", dependencies=[Depends(rate_limit("api"))])
HEAVY = [Depends(rate_limit("heavy"))]

MAX_BPMN_BYTES = 5 * 1024 * 1024


def get_llm() -> LLMProvider:
    """Dependency so tests can swap in a fake."""
    return LiteLLMProvider()


LLM = Annotated[LLMProvider, Depends(get_llm)]


class SegmentOut(BaseModel):
    segment_id: str
    speaker: str | None
    start_ts: float | None
    text: str


class MapOut(BaseModel):
    id: str
    project_id: str
    transcript_id: str | None  # None for a project's merged map
    version: int
    can_undo: bool
    model: dict[str, Any]
    bpmn_xml: str
    errors: list[ValidationError]  # live validation of the current version
    segments: list[SegmentOut]  # transcript lines, so the editor can show a node's source quotes
    diarization_available: bool | None
    conflicts: list[dict[str, Any]]  # merged maps: open disagreements between meetings, with options


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


def _segments(db: Session, pmap: ProcessMap) -> tuple[list[SegmentOut], bool | None]:
    """A transcript map cites `s3`; a merged map cites `<transcript_id>:s3` across meetings."""
    if pmap.transcript_id is not None:
        t = db.get_one(Transcript, pmap.transcript_id)
        return [SegmentOut.model_validate(s) for s in t.segments or []], t.diarization_available
    out, diarized = [], None
    for t in db.scalars(select(Transcript).where(Transcript.project_id == pmap.project_id)):
        out += [SegmentOut.model_validate({**s, "segment_id": f"{t.id}:{s['segment_id']}"}) for s in t.segments or []]
        diarized = False if t.diarization_available is False else diarized
    return out, diarized


def _out(db: Session, pmap: ProcessMap) -> MapOut:
    segments, diarized = _segments(db, pmap)
    return MapOut(
        id=pmap.id,
        project_id=pmap.project_id,
        transcript_id=pmap.transcript_id,
        version=pmap.current_version,
        can_undo=pmap.current_version > 1,
        model=pmap.model,
        bpmn_xml=pmap.bpmn_xml,
        errors=validate(ProcessModel.model_validate(pmap.model)),
        segments=segments,
        diarization_available=diarized,
        conflicts=[
            {"id": c.id, "kind": c.kind, "options": c.options}
            for c in db.scalars(
                select(Conflict).where(Conflict.project_id == pmap.project_id, Conflict.status == "open")
            )
        ]
        if pmap.transcript_id is None
        else [],
    )


@router.get("/{map_id}")
def get_map(map_id: str, db: DB) -> MapOut:
    return _out(db, _load(db, map_id))


@router.post("/{map_id}/chat", dependencies=HEAVY)
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
        audit(db, "edit", "map", pmap.id, via="chat", version=pmap.current_version, ops=len(ops))
        db.commit()
    return ChatOut(**_out(db, pmap).model_dump(), reply=plan.reply, ops=ops)


@router.post("/{map_id}/undo")
def undo(map_id: str, db: DB) -> MapOut:
    pmap = _load(db, map_id)
    try:
        maps.undo(db, pmap)
    except maps.NothingToUndo:
        raise HTTPException(409, "Nothing to undo") from None
    audit(db, "edit", "map", pmap.id, via="undo", version=pmap.current_version)
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
    audit(db, "edit", "map", pmap.id, via="visual", version=pmap.current_version)
    db.commit()
    return _out(db, pmap)


@router.get("/{map_id}/versions")
def list_versions(map_id: str, db: DB) -> list[VersionOut]:
    _load(db, map_id)
    return [VersionOut.model_validate(v, from_attributes=True) for v in maps.versions(db, map_id)]


EXPORT_TYPES = {
    "bpmn": "application/xml",
    "svg": "image/svg+xml",
    "png": "image/png",
    "md": "text/markdown; charset=utf-8",
}


@router.get("/{map_id}/export/{fmt}")
async def export(
    map_id: str, fmt: Literal["bpmn", "svg", "png", "md"], db: DB, request: Request, who: CurrentPrincipal
) -> Response:
    """Download the current version: BPMN 2.0 XML, SVG/PNG (rendered by bpmn-js), or a
    Markdown SOP whose steps cite their transcript quotes."""
    pmap = _load(db, map_id)
    model = ProcessModel.model_validate(pmap.model)
    if fmt == "bpmn":
        body: bytes = pmap.bpmn_xml.encode()
    elif fmt == "md":
        segments, _ = _segments(db, pmap)
        sources = {
            t.id: t.filename for t in db.scalars(select(Transcript).where(Transcript.project_id == pmap.project_id))
        }
        body = sop_markdown(model, {s.segment_id: s.model_dump() for s in segments}, sources).encode()
    else:
        await rate_limit("heavy")(request, who)  # image renders cost real CPU
        try:
            body = await run_in_threadpool(render_image, pmap.bpmn_xml, fmt)  # sync Playwright, off the event loop
        except ExportError as e:
            raise HTTPException(503, str(e)) from e
    audit(db, "export", "map", pmap.id, format=fmt, version=pmap.current_version)
    EXPORTS.labels(fmt).inc()
    db.commit()
    filename = re.sub(r"[^\w-]+", "_", model.name).strip("_") or "process"
    return Response(
        body,
        media_type=EXPORT_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}.{fmt}"'},
    )
