import re
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import maps
from app.audit import audit
from app.auth import DB, CurrentPrincipal
from app.db.models import Conflict, ProcessMap, Transcript
from app.demo import require_ai
from app.llm.provider import LiteLLMProvider, LLMProvider
from app.metrics import EXPORTS
from app.models.process import ProcessModel
from app.pipeline.edit import OpError, plan_edit
from app.pipeline.export import ExportError, render_image, render_pdf, sop_markdown
from app.pipeline.improve import Suggestion, ai_ideas, suggest
from app.pipeline.parse_bpmn import BpmnImportError, read_bpmn
from app.pipeline.sop_formats import sop_docx, sop_html
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


# Optimistic concurrency: GET returns the version as an ETag; edits send it back in If-Match.
# A mismatch is 412 Precondition Failed (someone else changed the map first). Without the
# header an edit applies to whatever is current (API clients that don't care).
IfMatch = Annotated[str | None, Header(alias="If-Match")]


def _expected(if_match: str | None) -> int | None:
    try:
        return maps.parse_if_match(if_match)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def _stale(e: maps.StaleVersion, expected: int | None) -> HTTPException:
    return HTTPException(
        412,
        f"This map was changed by someone else since you opened it (you have v{expected}, it's now v{e.current}).",
        headers={"ETag": f'"{e.current}"'},
    )


def _load_for_edit(db: Session, map_id: str, if_match: str | None) -> ProcessMap:
    """Lock the map row for this transaction and check the caller's version against it."""
    expected = _expected(if_match)
    pmap = maps.lock_map(db, map_id)
    if pmap is None:
        raise HTTPException(404, "Map not found")
    try:
        maps.check_version(pmap, expected)
    except maps.StaleVersion as e:
        raise _stale(e, expected) from None
    return pmap


def _etag(response: Response, pmap: ProcessMap) -> None:
    response.headers["ETag"] = f'"{pmap.current_version}"'


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
def get_map(map_id: str, db: DB, response: Response) -> MapOut:
    pmap = _load(db, map_id)
    _etag(response, pmap)
    return _out(db, pmap)


@router.post("/{map_id}/chat", dependencies=HEAVY)
def chat_edit(
    map_id: str, body: ChatIn, db: DB, llm: LLM, response: Response, who: CurrentPrincipal, if_match: IfMatch = None
) -> ChatOut:
    """Instruction -> LLM patch ops -> applied deterministically -> new version.

    The LLM call can take seconds, so no row lock is held during it: check the version,
    plan, then lock and check again before writing (someone may have edited meanwhile)."""
    require_ai(db, who.org_id)
    expected = _expected(if_match)
    pmap = _load(db, map_id)
    try:
        maps.check_version(pmap, expected)
    except maps.StaleVersion as e:
        raise _stale(e, expected) from None
    planned_on = pmap.current_version
    current = ProcessModel.model_validate(pmap.model)
    try:
        model, plan = plan_edit(llm, current, body.instruction)
    except OpError as e:
        raise HTTPException(422, f"Couldn't apply that edit: {e}") from e
    ops = [op.model_dump() for op in plan.ops]
    if ops:  # a clarifying question changes nothing and creates no version
        pmap = _load_for_edit(db, map_id, f'"{planned_on}"')  # the ops were planned against this version
        maps.commit_version(db, pmap, model, "chat", maps.current_positions(pmap), ops, body.instruction)
        audit(db, "edit", "map", pmap.id, via="chat", version=pmap.current_version, ops=len(ops))
        db.commit()
    _etag(response, pmap)
    return ChatOut(**_out(db, pmap).model_dump(), reply=plan.reply, ops=ops)


@router.post("/{map_id}/undo")
def undo(map_id: str, db: DB, response: Response, if_match: IfMatch = None) -> MapOut:
    pmap = _load_for_edit(db, map_id, if_match)
    try:
        maps.undo(db, pmap)
    except maps.NothingToUndo:
        raise HTTPException(409, "Nothing to undo") from None
    audit(db, "edit", "map", pmap.id, via="undo", version=pmap.current_version)
    db.commit()
    _etag(response, pmap)
    return _out(db, pmap)


@router.put("/{map_id}/bpmn")
def save_bpmn(
    map_id: str,
    db: DB,
    response: Response,
    xml: Annotated[bytes, Body(media_type="application/xml")],
    if_match: IfMatch = None,
) -> MapOut:
    """Visual edit: BPMN XML from the editor -> ProcessModel (matched by id) -> new version.
    The editor's node positions are kept; the stored XML is regenerated from the model."""
    if len(xml) > MAX_BPMN_BYTES:
        raise HTTPException(413, "BPMN document too large")
    pmap = _load_for_edit(db, map_id, if_match)
    try:
        model, positions = read_bpmn(xml, ProcessModel.model_validate(pmap.model))
    except BpmnImportError as e:
        raise HTTPException(422, str(e)) from e
    maps.commit_version(db, pmap, model, "visual", positions)
    audit(db, "edit", "map", pmap.id, via="visual", version=pmap.current_version)
    db.commit()
    _etag(response, pmap)
    return _out(db, pmap)


REVIEW_BELOW = 0.75  # steps under this confidence are flagged for a person to check


class ReviewItem(BaseModel):
    node_id: str
    name: str
    type: str
    lane: str
    confidence: float
    cited: bool
    reason: str | None  # "No source in any meeting" / "Low confidence (55%)" / None
    reviewed: bool


@router.get("/{map_id}/review")
def review_queue(map_id: str, db: DB) -> list[ReviewItem]:
    """Every step and decision the AI produced, ordered so reviewers start where it is least
    sure: unchecked first, then uncited, then by confidence (lowest first). Steps added by hand
    aren't listed: there's nothing to second-guess."""
    pmap = _load(db, map_id)
    model = ProcessModel.model_validate(pmap.model)
    lanes = {x.id: x.name for x in model.lanes}
    done = set(pmap.reviewed_node_ids or [])
    items = []
    for n in model.nodes:
        if n.user_added or n.type in ("start_event", "end_event") or (n.type.endswith("gateway") and not n.name):
            continue
        cited = bool(n.source_segment_ids)
        reason = (
            "No source in any meeting"
            if not cited
            else f"Low confidence ({round(n.confidence * 100)}%)"
            if n.confidence < REVIEW_BELOW
            else None
        )
        items.append(
            ReviewItem(
                node_id=n.id, name=n.name, type=n.type, lane=lanes.get(n.lane_id, ""), confidence=n.confidence,
                cited=cited, reason=reason, reviewed=n.id in done,
            )
        )  # fmt: skip
    return sorted(items, key=lambda i: (i.reviewed, i.reason is None, i.cited, i.confidence))


class ReviewIn(BaseModel):
    checked: bool = True


@router.post("/{map_id}/review/{node_id}")
def mark_reviewed(map_id: str, node_id: str, db: DB, body: ReviewIn | None = None) -> dict[str, bool]:
    """Mark a step as checked by a person (or un-mark it). Not a map edit: no new version."""
    pmap = _load(db, map_id)
    if node_id not in {n["id"] for n in pmap.model["nodes"]}:
        raise HTTPException(404, "No such step on this map")
    done = [x for x in (pmap.reviewed_node_ids or []) if x != node_id]
    checked = body.checked if body else True
    pmap.reviewed_node_ids = done + [node_id] if checked else done  # reassign: JSON isn't change-tracked
    audit(db, "review_step", "map", pmap.id, checked=checked)
    db.commit()
    return {"checked": checked}


class SuggestionOut(BaseModel):
    id: str
    kind: str  # automate | handoff | approvals | ai
    title: str
    detail: str
    node_ids: list[str]


@router.get("/{map_id}/improvements")
def improvements(map_id: str, db: DB) -> list[SuggestionOut]:
    """Where the process could improve, from the map's structure (free, explainable rules)."""
    model = ProcessModel.model_validate(_load(db, map_id).model)
    return [SuggestionOut(**s.__dict__) for s in suggest(model)]


@router.post("/{map_id}/improvements/ai", dependencies=HEAVY)
def improvements_ai(map_id: str, db: DB, llm: LLM, who: CurrentPrincipal) -> list[SuggestionOut]:
    """More ideas from the AI, beyond the rules. Costs credits, so only on request."""
    require_ai(db, who.org_id)
    pmap = _load(db, map_id)
    model = ProcessModel.model_validate(pmap.model)
    rules: list[Suggestion] = suggest(model)
    ideas = ai_ideas(llm, model, rules)
    audit(db, "ai_improvements", "map", pmap.id, ideas=len(ideas))
    db.commit()
    return [SuggestionOut(**s.__dict__) for s in ideas]


class PushedOut(BaseModel):
    target: str
    url: str


@router.post("/{map_id}/push/camunda", dependencies=HEAVY)
def push_camunda(map_id: str, db: DB) -> PushedOut:
    """Create this map's current version as a BPMN file in Camunda Web Modeler."""
    from app.integrations import camunda

    pmap = _load(db, map_id)
    if not camunda.configured():
        raise HTTPException(501, "Camunda isn't set up on this server (CAMUNDA_* settings)")
    name = ProcessModel.model_validate(pmap.model).name
    try:
        pushed = camunda.push(f"{name} v{pmap.current_version}", pmap.bpmn_xml)
    except camunda.CamundaError as e:
        raise HTTPException(502, str(e)) from e
    audit(db, "export", "map", pmap.id, format="camunda", version=pmap.current_version)
    db.commit()
    return PushedOut(target="camunda", url=pushed.url)


@router.get("/{map_id}/versions")
def list_versions(map_id: str, db: DB) -> list[VersionOut]:
    _load(db, map_id)
    return [VersionOut.model_validate(v, from_attributes=True) for v in maps.versions(db, map_id)]


EXPORT_TYPES = {
    "bpmn": "application/xml",
    "svg": "image/svg+xml",
    "png": "image/png",
    "md": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


@router.get("/{map_id}/export/{fmt}")
async def export(
    map_id: str,
    fmt: Literal["bpmn", "svg", "png", "md", "docx", "pdf"],
    db: DB,
    request: Request,
    who: CurrentPrincipal,
) -> Response:
    """Download the current version: BPMN 2.0 XML, SVG/PNG (rendered by bpmn-js), or the written
    SOP (Markdown, Word or PDF) whose steps cite their transcript quotes."""
    pmap = _load(db, map_id)
    model = ProcessModel.model_validate(pmap.model)
    if fmt == "bpmn":
        body: bytes = pmap.bpmn_xml.encode()
    elif fmt in ("md", "docx", "pdf"):
        segments, _ = _segments(db, pmap)
        sources = {
            t.id: t.filename for t in db.scalars(select(Transcript).where(Transcript.project_id == pmap.project_id))
        }
        md = sop_markdown(model, {s.segment_id: s.model_dump() for s in segments}, sources)
        if fmt == "md":
            body = md.encode()
        elif fmt == "docx":
            body = sop_docx(md)
        else:
            await rate_limit("heavy")(request, who)
            try:
                body = await run_in_threadpool(render_pdf, sop_html(md))
            except ExportError as e:
                raise HTTPException(503, str(e)) from e
    else:
        await rate_limit("heavy")(request, who)  # image renders cost real CPU
        try:
            body = await run_in_threadpool(
                render_image, pmap.bpmn_xml, "svg" if fmt == "svg" else "png"
            )  # sync Playwright, off the event loop
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
