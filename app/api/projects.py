import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import insights, maps, storage
from app.agenda import build_agenda
from app.audit import audit
from app.auth import DB, CurrentPrincipal
from app.core.config import get_settings
from app.db.models import AuditLog, Conflict, Job, MapVersion, Organization, ProcessMap, Project, Signoff, Transcript
from app.models.process import ProcessModel
from app.pipeline import ingest
from app.pipeline.edit import AnyOp, ResolveOpenQuestion, apply_ops
from app.pipeline.gaps import Gap, find_gaps
from app.pipeline.merge import CannotApply, resolution_ops, variant_ops
from app.pipeline.transcribe import AUDIO_EXTENSIONS, audio
from app.projects import delete_project
from app.ratelimit import check_quota, jobs_this_month, rate_limit

router = APIRouter(dependencies=[Depends(rate_limit("api"))])
HEAVY = [Depends(rate_limit("heavy"))]

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_AUDIO_BYTES = 1024 * 1024 * 1024  # ~1 GB: hours of WAV


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    retention_days: int | None = Field(default=None, ge=1)


class JobOut(BaseModel):
    id: str
    transcript_id: str
    status: str
    error: str | None
    map_id: str | None  # this transcript's own map; the merged one is on the project


class TranscriptOut(BaseModel):
    id: str
    project_id: str
    filename: str
    purpose: str = "meeting"  # meeting | policy
    segment_count: int | None  # text uploads
    duration_seconds: float | None  # audio uploads
    content_expired: bool = False
    created_at: datetime | None = None
    latest_job: JobOut | None = None  # most recent processing run, for live status in the UI


class ProjectOut(BaseModel):
    id: str
    name: str
    retention_days: int | None
    merged_map_id: str | None
    map_version: int | None  # merged map's current version (for the "revised … · vN" line)
    revised_at: datetime | None  # when the merged map last changed
    open_conflicts: int  # meetings disagreeing with each other
    open_policy_differences: int
    transcripts: list[TranscriptOut]


class QuoteOut(BaseModel):
    text: str | None  # None: deleted by the retention policy
    speaker: str | None
    role: str | None
    meeting: str
    start_ts: float | None
    policy: bool


class SideOut(BaseModel):
    label: str
    quotes: list[QuoteOut]


class ConflictOut(BaseModel):
    id: str
    origin: str  # meeting | policy
    kind: str
    description: str
    options: list[str]
    node_ids: list[str]
    sources: list[dict[str, Any]]
    sides: list[SideOut] = []  # who said what, per side
    owner_side: int | None = None  # the side the process owner backs, if only one does
    status: str
    resolution: str | None


class SpeakerOut(BaseModel):
    name: str
    role: str | None
    lines: int
    meetings: int


class SpeakerRoleIn(BaseModel):
    role: Literal["owner", "performer", "observer"] | None


class GapOut(BaseModel):
    id: str
    kind: str
    node_ids: list[str]
    description: str
    question: str


class AuditOut(BaseModel):
    action: str
    target_type: str
    target_id: str
    api_key_id: str | None
    details: dict[str, Any]
    created_at: datetime


def _project(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)  # tenant-scoped: another org's project is simply not found
    if p is None:
        raise HTTPException(404, "Project not found")
    return p


def _transcript_out(t: Transcript, duration: float | None = None, job: Job | None = None) -> TranscriptOut:
    return TranscriptOut(
        id=t.id,
        project_id=t.project_id,
        filename=t.filename,
        purpose=t.purpose,
        segment_count=len(t.segments) if t.segments else None,
        duration_seconds=duration,
        content_expired=t.content_expired_at is not None,
        created_at=t.created_at,
        latest_job=_job_out(job) if job else None,
    )


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, db: DB) -> ProjectOut:
    p = Project(name=body.name, retention_days=body.retention_days)
    db.add(p)
    db.flush()
    audit(db, "create", "project", p.id, retention_days=body.retention_days)
    db.commit()
    return get_project(p.id, db)


@router.get("/projects")
def list_projects(db: DB) -> list[ProjectOut]:
    return [get_project(p.id, db) for p in db.scalars(select(Project).order_by(Project.created_at))]


@router.get("/projects/{project_id}")
def get_project(project_id: str, db: DB) -> ProjectOut:
    p = _project(db, project_id)
    transcripts = db.scalars(
        select(Transcript).where(Transcript.project_id == p.id).order_by(Transcript.created_at)
    ).all()
    latest: dict[str, Job] = {}
    for job in db.scalars(
        select(Job).where(Job.transcript_id.in_([t.id for t in transcripts])).order_by(Job.created_at)
    ):
        latest[job.transcript_id] = job  # ordered by time: the last one wins
    open_by_origin = db.scalars(
        select(Conflict.origin).where(Conflict.project_id == p.id, Conflict.status == "open")
    ).all()
    merged = db.get(ProcessMap, p.merged_map_id) if p.merged_map_id else None
    revised = (
        db.scalar(
            select(MapVersion.created_at).where(
                MapVersion.map_id == merged.id, MapVersion.version == merged.current_version
            )
        )
        if merged
        else None
    )
    return ProjectOut(
        id=p.id,
        name=p.name,
        retention_days=p.retention_days,
        merged_map_id=p.merged_map_id,
        map_version=merged.current_version if merged else None,
        revised_at=revised,
        open_conflicts=open_by_origin.count("meeting"),
        open_policy_differences=open_by_origin.count("policy"),
        transcripts=[_transcript_out(t, job=latest.get(t.id)) for t in transcripts],
    )


@router.delete("/projects/{project_id}")
def remove_project(project_id: str, db: DB) -> dict[str, int]:
    counts = delete_project(db, _project(db, project_id))
    db.commit()
    return counts


@router.post("/projects/{project_id}/transcripts", status_code=201, dependencies=HEAVY)
async def upload_transcript(
    project_id: str, file: UploadFile, db: DB, purpose: Literal["meeting", "policy"] = "meeting"
) -> TranscriptOut:
    """Upload a meeting (transcript or recording), or with ?purpose=policy a policy/SOP
    document (.docx/.txt) that the map is compared against but never merged with."""
    project = _project(db, project_id)
    filename = Path(file.filename or "").name  # never trust a client path
    if Path(filename).suffix.lower() in AUDIO_EXTENSIONS:
        if purpose == "policy":
            raise HTTPException(400, "A policy document must be text: .docx or .txt")
        return await run_in_threadpool(_upload_audio, project, file, filename, db)  # big file I/O + ffprobe
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    try:
        segments = ingest.parse(filename, data)  # reject unparseable files at the door
    except ingest.UnsupportedFile as e:
        raise HTTPException(400, f"{e} or audio ({', '.join(AUDIO_EXTENSIONS)})") from e
    if not segments:
        raise HTTPException(400, "Transcript contains no text")
    t = _new_transcript(db, project, filename)
    t.purpose = purpose
    storage.put(t.storage_key, data)
    audit(db, "upload", "transcript", t.id, project_id=project.id, bytes=len(data), kind="text", purpose=purpose)
    db.commit()
    return _transcript_out(t).model_copy(update={"segment_count": len(segments)})


def _new_transcript(db: Session, project: Project, filename: str) -> Transcript:
    t = Transcript(project_id=project.id, filename=filename, storage_key="")
    db.add(t)
    db.flush()
    t.storage_key = f"{storage.project_prefix(project.organization_id, project.id)}transcripts/{t.id}/{filename}"
    return t


def _upload_audio(project: Project, file: UploadFile, filename: str, db: Session) -> TranscriptOut:
    # Spooled to disk, never fully in memory; ffprobe needs a seekable file anyway (m4a/mp4).
    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp.flush()
        size = tmp.tell()
        if size > MAX_AUDIO_BYTES:
            raise HTTPException(413, f"Audio larger than {MAX_AUDIO_BYTES // 1024**3} GB")
        try:
            seconds = audio.duration(Path(tmp.name))
        except audio.AudioError as e:
            raise HTTPException(400, f"Not a readable audio file: {e}") from e
        t = _new_transcript(db, project, filename)
        storage.put_file(t.storage_key, Path(tmp.name))
    audit(db, "upload", "transcript", t.id, project_id=project.id, bytes=size, kind="audio")
    db.commit()
    return _transcript_out(t, seconds)


@router.post("/transcripts/{transcript_id}/process", status_code=202, dependencies=HEAVY)
async def process_transcript(transcript_id: str, request: Request, db: DB) -> JobOut:
    t = db.get(Transcript, transcript_id)
    if t is None:
        raise HTTPException(404, "Transcript not found")
    if t.content_expired_at is not None:
        raise HTTPException(410, "Transcript content was deleted by the retention policy")
    check_quota(db, t.organization_id)
    job = Job(transcript_id=transcript_id, status="queued")
    db.add(job)
    db.flush()
    audit(db, "process", "transcript", t.id, job_id=job.id)
    db.commit()
    await request.app.state.arq.enqueue_job(
        "process_transcript", job.id, _job_id=job.id, _queue_name=get_settings().job_queue
    )
    return _job_out(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: DB) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return _job_out(job)


def _job_out(job: Job) -> JobOut:
    return JobOut(id=job.id, transcript_id=job.transcript_id, status=job.status, error=job.error, map_id=job.map_id)


def _conflict_out(c: Conflict, index: dict[str, insights.Quote]) -> ConflictOut:
    ss = insights.sides(c, index)
    out = ConflictOut.model_validate(c, from_attributes=True)
    return out.model_copy(
        update={
            "sides": [SideOut(label=s.label, quotes=[QuoteOut(**q.__dict__) for q in s.quotes]) for s in ss],
            "owner_side": insights.owner_side(ss),
        }
    )


@router.get("/projects/{project_id}/conflicts")
def list_conflicts(
    project_id: str, db: DB, status: str | None = None, origin: Literal["meeting", "policy"] | None = None
) -> list[ConflictOut]:
    p = _project(db, project_id)
    q = select(Conflict).where(Conflict.project_id == p.id).order_by(Conflict.created_at)
    if status:
        q = q.where(Conflict.status == status)
    if origin:
        q = q.where(Conflict.origin == origin)
    index = insights.segment_index(db, p.id)
    return [_conflict_out(c, index) for c in db.scalars(q)]


@router.get("/projects/{project_id}/speakers")
def list_speakers(project_id: str, db: DB) -> list[SpeakerOut]:
    return [SpeakerOut.model_validate(s) for s in insights.speakers(db, _project(db, project_id))]


@router.put("/projects/{project_id}/speakers/{name}")
def set_speaker_role(project_id: str, name: str, body: SpeakerRoleIn, db: DB) -> SpeakerOut:
    p = _project(db, project_id)
    known = {s["name"]: s for s in insights.speakers(db, p)}
    if name not in known:
        raise HTTPException(404, "No speaker by that name in this project's meetings")
    roles = dict(p.speaker_roles or {})
    if body.role:
        roles[name] = body.role
    else:
        roles.pop(name, None)
    p.speaker_roles = roles  # reassign: JSON columns don't track in-place changes
    audit(db, "set_speaker_role", "project", p.id, role=body.role)
    db.commit()
    return SpeakerOut.model_validate({**known[name], "role": body.role})


def _gaps(db: Session, p: Project) -> list[Gap]:
    if not p.merged_map_id:
        return []
    model = ProcessModel.model_validate(db.get_one(ProcessMap, p.merged_map_id).model)
    dismissed = set(p.dismissed_gaps or [])
    return [g for g in find_gaps(model) if g.id not in dismissed]


@router.get("/projects/{project_id}/gaps")
def list_gaps(project_id: str, db: DB) -> list[GapOut]:
    return [GapOut(**g.__dict__) for g in _gaps(db, _project(db, project_id))]


@router.post("/projects/{project_id}/gaps/{gap_id}/dismiss")
def dismiss_gap(project_id: str, gap_id: str, db: DB) -> dict[str, str]:
    p = _project(db, project_id)
    if gap_id not in {g.id for g in _gaps(db, p)}:
        raise HTTPException(404, "No such open gap")
    p.dismissed_gaps = [*(p.dismissed_gaps or []), gap_id]
    audit(db, "dismiss_gap", "project", p.id, gap_id=gap_id)
    db.commit()
    return {"status": "dismissed"}


@router.get("/projects/{project_id}/agenda")
def agenda(project_id: str, db: DB) -> Response:
    """The next meeting's agenda as Markdown (template-built: no LLM)."""
    p = _project(db, project_id)
    index = insights.segment_index(db, p.id)
    open_ = db.scalars(
        select(Conflict).where(Conflict.project_id == p.id, Conflict.status == "open").order_by(Conflict.created_at)
    ).all()
    # Meeting disagreements first (numbered like the UI's points), then policy differences.
    ordered = sorted(open_, key=lambda c: c.origin != "meeting")
    model = ProcessModel.model_validate(db.get_one(ProcessMap, p.merged_map_id).model) if p.merged_map_id else None
    body = build_agenda(p.name, [(c, insights.sides(c, index)) for c in ordered], _gaps(db, p), model, index)
    audit(db, "export", "project", p.id, format="agenda")
    db.commit()
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in p.name).strip() or "process"
    return Response(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="Next meeting - {safe}.md"'},
    )


class VariantIn(BaseModel):
    question: str = Field(min_length=1, max_length=200)  # what decides it, e.g. "Which region?"
    labels: list[str]  # one per option, e.g. ["North", "South"]


class ResolveIn(BaseModel):
    # Index into the conflict's options to apply it to the map; null = "I fixed the map myself".
    option: int | None = None
    # "Both are true": keep every option as a branch of a new decision.
    variant: VariantIn | None = None
    # Policy differences: keep the map as is and record why.
    note: Literal["deviation", "dismissed"] | None = None


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: str,
    db: DB,
    body: ResolveIn | None = None,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,  # merged map version, like map edits
) -> ConflictOut:
    """Settle a disagreement: apply the chosen option to the merged map (if any) and drop its
    open question, in one new map version."""
    c = db.get(Conflict, conflict_id)
    if c is None:
        raise HTTPException(404, "Conflict not found")
    if c.status != "open":
        raise HTTPException(409, "Conflict is already resolved")
    body = body or ResolveIn()
    choice, variant = body.option, body.variant
    if sum(x is not None for x in (choice, variant, body.note)) > 1:
        raise HTTPException(400, "Choose one: an option, a variant, or a note")
    if body.note and c.origin != "policy":
        raise HTTPException(400, "Notes are for policy differences; pick an option or a variant")
    project = _project(db, c.project_id)
    if project.merged_map_id:
        pmap = maps.lock_map(db, project.merged_map_id)
        assert pmap is not None
        try:
            expected = maps.parse_if_match(if_match)
            maps.check_version(pmap, expected)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except maps.StaleVersion as e:
            raise HTTPException(
                412, f"The map changed since you loaded it (it's now v{e.current}). Reload and try again."
            ) from None
        model = ProcessModel.model_validate(pmap.model)
        ops: list[AnyOp] = []
        try:
            if choice is not None:
                if not c.options:
                    raise CannotApply("this difference has no options to apply; note it or dismiss it")
                ops += resolution_ops(c.kind, c.node_ids, c.options, choice, model)
            elif variant is not None:
                ops += variant_ops(c.kind, c.node_ids, c.options, variant.question, variant.labels, model)
        except CannotApply as e:
            raise HTTPException(422, f"Can't apply that automatically: {e}") from e
        qid = f"conflict_{c.id}"
        if any(q.id == qid for q in model.open_questions):
            ops.append(ResolveOpenQuestion(op="resolve_open_question", question_id=qid))
        if ops:
            maps.commit_version(
                db, pmap, apply_ops(model, ops), "resolve", maps.current_positions(pmap), [o.model_dump() for o in ops]
            )
    if variant is not None:
        resolution: str | None = f"Both, by case ({variant.question.strip()}): " + "; ".join(
            f"{lab.strip()}: {opt}" for lab, opt in zip(variant.labels, c.options, strict=True)
        )
    elif body.note:
        resolution = {"deviation": "Noted as a deviation from the policy", "dismissed": "Dismissed"}[body.note]
    else:
        resolution = c.options[choice] if choice is not None else None
    c.status, c.resolution = "resolved", resolution
    audit(
        db, "resolve_conflict", "conflict", c.id, project_id=c.project_id, applied_option=choice,
        variant=variant is not None, note=body.note,
    )  # fmt: skip
    db.commit()
    return _conflict_out(c, insights.segment_index(db, c.project_id))


class InboxItem(BaseModel):
    kind: Literal["disagreement", "policy", "gap", "signoff", "failed"]
    project_id: str
    project_name: str
    ref: str | None  # D1 / P1 / G1, as the process page shows them
    title: str
    detail: str | None
    at: datetime | None
    tab: str  # where it's settled: review | sources | signoff


@router.get("/inbox")
def inbox(db: DB) -> list[InboxItem]:
    """Everything waiting on someone, across all processes: open disagreements and policy
    differences, gaps, sign-offs that came back, and files that failed to process."""
    items: list[InboxItem] = []
    for p in db.scalars(select(Project).order_by(Project.created_at)):

        def add(
            kind: str, ref: str | None, title: str, detail: str | None, at: datetime | None, tab: str, p: Project = p
        ) -> None:
            items.append(
                InboxItem.model_validate(
                    {"kind": kind, "project_id": p.id, "project_name": p.name, "ref": ref, "title": title,
                     "detail": detail, "at": at, "tab": tab}
                )
            )  # fmt: skip

        open_ = db.scalars(
            select(Conflict).where(Conflict.project_id == p.id, Conflict.status == "open").order_by(Conflict.created_at)
        ).all()
        for origin, prefix, kind in (("meeting", "D", "disagreement"), ("policy", "P", "policy")):
            for k, c in enumerate((c for c in open_ if c.origin == origin), 1):
                add(kind, f"{prefix}{k}", c.description, None, c.created_at, "review")
        for k, g in enumerate(_gaps(db, p), 1):
            add("gap", f"G{k}", g.description, g.question, None, "review")
        for s in db.scalars(select(Signoff).where(Signoff.project_id == p.id, Signoff.decision.is_not(None))):
            word = "approved their part" if s.decision == "approved" else "asked for changes"
            add("signoff", None, f"{s.name} {word}", s.comment, s.decided_at, "signoff")
        transcripts = db.scalars(select(Transcript).where(Transcript.project_id == p.id)).all()
        latest: dict[str, Job] = {}
        for job in db.scalars(
            select(Job).where(Job.transcript_id.in_([t.id for t in transcripts])).order_by(Job.created_at)
        ):
            latest[job.transcript_id] = job  # ordered by time: the last one wins
        for t in transcripts:
            last = latest.get(t.id)
            if last and last.status == "failed":
                add("failed", None, f"{t.filename} failed to process", last.error, last.updated_at, "sources")
    return items


class UsageOut(BaseModel):
    jobs_this_month: int
    monthly_jobs_quota: int | None
    rate_limit_per_minute: int
    rate_limit_heavy_per_minute: int


@router.get("/usage")
def usage(db: DB, who: CurrentPrincipal) -> UsageOut:
    s = get_settings()
    return UsageOut(
        jobs_this_month=jobs_this_month(db),
        monthly_jobs_quota=db.get_one(Organization, who.org_id).monthly_jobs_quota,
        rate_limit_per_minute=s.rate_limit_per_minute,
        rate_limit_heavy_per_minute=s.rate_limit_heavy_per_minute,
    )


@router.get("/audit")
def list_audit(db: DB, limit: int = 100) -> list[AuditOut]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 1000)))
    return [AuditOut.model_validate(r, from_attributes=True) for r in rows]
