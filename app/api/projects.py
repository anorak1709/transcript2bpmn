import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import maps, storage
from app.audit import audit
from app.auth import DB, CurrentPrincipal
from app.core.config import get_settings
from app.db.models import AuditLog, Conflict, Job, Organization, ProcessMap, Project, Transcript
from app.models.process import ProcessModel
from app.pipeline import ingest
from app.pipeline.edit import AnyOp, ResolveOpenQuestion, apply_ops
from app.pipeline.merge import CannotApply, resolution_ops
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
    open_conflicts: int
    transcripts: list[TranscriptOut]


class ConflictOut(BaseModel):
    id: str
    kind: str
    description: str
    options: list[str]
    node_ids: list[str]
    sources: list[dict[str, Any]]
    status: str
    resolution: str | None


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
    open_conflicts = db.scalars(select(Conflict.id).where(Conflict.project_id == p.id, Conflict.status == "open")).all()
    return ProjectOut(
        id=p.id,
        name=p.name,
        retention_days=p.retention_days,
        merged_map_id=p.merged_map_id,
        open_conflicts=len(open_conflicts),
        transcripts=[_transcript_out(t, job=latest.get(t.id)) for t in transcripts],
    )


@router.delete("/projects/{project_id}")
def remove_project(project_id: str, db: DB) -> dict[str, int]:
    counts = delete_project(db, _project(db, project_id))
    db.commit()
    return counts


@router.post("/projects/{project_id}/transcripts", status_code=201, dependencies=HEAVY)
async def upload_transcript(project_id: str, file: UploadFile, db: DB) -> TranscriptOut:
    project = _project(db, project_id)
    filename = Path(file.filename or "").name  # never trust a client path
    if Path(filename).suffix.lower() in AUDIO_EXTENSIONS:
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
    storage.put(t.storage_key, data)
    audit(db, "upload", "transcript", t.id, project_id=project.id, bytes=len(data), kind="text")
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


@router.get("/projects/{project_id}/conflicts")
def list_conflicts(project_id: str, db: DB, status: str | None = None) -> list[ConflictOut]:
    q = select(Conflict).where(Conflict.project_id == _project(db, project_id).id).order_by(Conflict.created_at)
    if status:
        q = q.where(Conflict.status == status)
    return [ConflictOut.model_validate(c, from_attributes=True) for c in db.scalars(q)]


class ResolveIn(BaseModel):
    # Index into the conflict's options to apply it to the map; null = "I fixed the map myself".
    option: int | None = None


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id: str, db: DB, body: ResolveIn | None = None) -> ConflictOut:
    """Settle a disagreement: apply the chosen option to the merged map (if any) and drop its
    open question, in one new map version."""
    c = db.get(Conflict, conflict_id)
    if c is None:
        raise HTTPException(404, "Conflict not found")
    if c.status != "open":
        raise HTTPException(409, "Conflict is already resolved")
    choice = body.option if body else None
    project = _project(db, c.project_id)
    if project.merged_map_id:
        pmap = db.get_one(ProcessMap, project.merged_map_id)
        model = ProcessModel.model_validate(pmap.model)
        ops: list[AnyOp] = []
        if choice is not None:
            try:
                ops += resolution_ops(c.kind, c.node_ids, c.options, choice, model)
            except CannotApply as e:
                raise HTTPException(422, f"Can't apply that option automatically: {e}") from e
        qid = f"conflict_{c.id}"
        if any(q.id == qid for q in model.open_questions):
            ops.append(ResolveOpenQuestion(op="resolve_open_question", question_id=qid))
        if ops:
            maps.commit_version(
                db, pmap, apply_ops(model, ops), "resolve", maps.current_positions(pmap), [o.model_dump() for o in ops]
            )
    c.status, c.resolution = "resolved", (c.options[choice] if choice is not None else None)
    audit(db, "resolve_conflict", "conflict", c.id, project_id=c.project_id, applied_option=choice)
    db.commit()
    return ConflictOut.model_validate(c, from_attributes=True)


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
