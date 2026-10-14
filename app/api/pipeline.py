import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import storage
from app.db.base import get_db
from app.db.models import Job, Transcript
from app.pipeline import ingest
from app.pipeline.transcribe import AUDIO_EXTENSIONS, audio

router = APIRouter()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_AUDIO_BYTES = 1024 * 1024 * 1024  # ~1 GB: hours of WAV


DB = Annotated[Session, Depends(get_db)]


class TranscriptOut(BaseModel):
    id: str
    filename: str
    segment_count: int | None  # text uploads
    duration_seconds: float | None  # audio uploads


class JobOut(BaseModel):
    id: str
    transcript_id: str
    status: str
    error: str | None
    map_id: str | None


@router.post("/transcripts", status_code=201)
async def upload_transcript(file: UploadFile, db: DB) -> TranscriptOut:
    filename = file.filename or ""
    if Path(filename).suffix.lower() in AUDIO_EXTENSIONS:
        return await run_in_threadpool(_upload_audio, file, filename, db)  # big file I/O + ffprobe
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    try:
        segments = ingest.parse(filename, data)  # reject unparseable files at the door
    except ingest.UnsupportedFile as e:
        raise HTTPException(400, f"{e} or audio ({', '.join(AUDIO_EXTENSIONS)})") from e
    if not segments:
        raise HTTPException(400, "Transcript contains no text")

    t = Transcript(filename=filename, storage_key="")
    db.add(t)
    db.flush()
    t.storage_key = f"transcripts/{t.id}/{filename}"
    storage.put(t.storage_key, data)
    db.commit()
    return TranscriptOut(id=t.id, filename=filename, segment_count=len(segments), duration_seconds=None)


def _upload_audio(file: UploadFile, filename: str, db: Session) -> TranscriptOut:
    # Spooled to disk, never fully in memory; ffprobe needs a seekable file anyway (m4a/mp4).
    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp.flush()
        if tmp.tell() > MAX_AUDIO_BYTES:
            raise HTTPException(413, f"Audio larger than {MAX_AUDIO_BYTES // 1024**3} GB")
        try:
            seconds = audio.duration(Path(tmp.name))
        except audio.AudioError as e:
            raise HTTPException(400, f"Not a readable audio file: {e}") from e

        t = Transcript(filename=filename, storage_key="")
        db.add(t)
        db.flush()
        t.storage_key = f"transcripts/{t.id}/{filename}"
        storage.put_file(t.storage_key, Path(tmp.name))
    db.commit()
    return TranscriptOut(id=t.id, filename=filename, segment_count=None, duration_seconds=seconds)


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


def _job_out(job: Job) -> JobOut:
    return JobOut(id=job.id, transcript_id=job.transcript_id, status=job.status, error=job.error, map_id=job.map_id)
