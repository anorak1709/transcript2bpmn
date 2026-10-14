from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import storage
from app.db.base import SessionLocal
from app.db.models import Job, ProcessMap, Transcript
from app.pipeline import ingest

router = APIRouter()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


DB = Annotated[Session, Depends(get_db)]


class TranscriptOut(BaseModel):
    id: str
    filename: str
    segment_count: int


class JobOut(BaseModel):
    id: str
    transcript_id: str
    status: str
    error: str | None
    map_id: str | None


class MapOut(BaseModel):
    id: str
    transcript_id: str
    model: dict[str, Any]
    bpmn_xml: str


@router.post("/transcripts", status_code=201)
async def upload_transcript(file: UploadFile, db: DB) -> TranscriptOut:
    filename = file.filename or ""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    try:
        segments = ingest.parse(filename, data)  # reject unparseable files at the door
    except ingest.UnsupportedFile as e:
        raise HTTPException(400, str(e)) from e
    if not segments:
        raise HTTPException(400, "Transcript contains no text")

    t = Transcript(filename=filename, storage_key="")
    db.add(t)
    db.flush()
    t.storage_key = f"transcripts/{t.id}/{filename}"
    storage.put(t.storage_key, data)
    db.commit()
    return TranscriptOut(id=t.id, filename=filename, segment_count=len(segments))


@router.post("/transcripts/{transcript_id}/process", status_code=202)
async def process_transcript(transcript_id: str, request: Request, db: DB) -> JobOut:
    if db.get(Transcript, transcript_id) is None:
        raise HTTPException(404, "Transcript not found")
    job = Job(transcript_id=transcript_id, status="queued")
    db.add(job)
    db.commit()
    await request.app.state.arq.enqueue_job("process_transcript", job.id, _job_id=job.id)
    return _job_out(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: DB) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return _job_out(job)


@router.get("/maps/{map_id}")
def get_map(map_id: str, db: DB) -> MapOut:
    m = db.get(ProcessMap, map_id)
    if m is None:
        raise HTTPException(404, "Map not found")
    return MapOut(id=m.id, transcript_id=m.transcript_id, model=m.model, bpmn_xml=m.bpmn_xml)


def _job_out(job: Job) -> JobOut:
    return JobOut(id=job.id, transcript_id=job.transcript_id, status=job.status, error=job.error, map_id=job.map_id)
