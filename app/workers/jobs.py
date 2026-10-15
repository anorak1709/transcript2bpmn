import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from app import storage
from app.db.models import Job, Project, Transcript
from app.db.tenancy import bind, system_session
from app.llm.provider import LiteLLMProvider, LLMProvider
from app.maps import create_map
from app.pipeline import ingest
from app.pipeline.run import model_from_segments, prepare_segments
from app.pipeline.transcribe import AUDIO_EXTENSIONS, Transcriber, get_transcriber
from app.projects import merge_into_project, purge_expired

log = logging.getLogger(__name__)


def run_job(job_id: str, llm: LLMProvider | None = None, transcriber: Transcriber | None = None) -> None:
    """Run the full pipeline for one job, recording each stage on the Job row: the transcript
    gets its own map, then is merged into its project's map."""
    with system_session() as db:
        org_id = db.get_one(Job, job_id).organization_id
        bind(db, org_id)  # the job id is trusted (we enqueued it); everything after is org-scoped
        job = db.get_one(Job, job_id)
        transcript = db.get_one(Transcript, job.transcript_id)
        llm = llm or LiteLLMProvider()

        def stage(name: str) -> None:
            job.status = name
            db.commit()

        try:
            suffix = Path(transcript.filename).suffix.lower()
            if suffix in AUDIO_EXTENSIONS:
                stage("transcribing")
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / f"audio{suffix}"
                    storage.download(transcript.storage_key, path)
                    result = (transcriber or get_transcriber()).transcribe(path)
                raw = result.segments
                transcript.diarization_available = result.diarization_available
                stage("normalizing")
            else:
                stage("normalizing")
                raw = ingest.parse(transcript.filename, storage.get(transcript.storage_key))
            segments = prepare_segments(raw, llm)
            transcript.segments = [s.model_dump() for s in segments]

            stage("extracting")
            model = model_from_segments(segments, llm).model  # extract + validate/repair

            stage("converting")
            pmap = create_map(db, transcript.project_id, transcript.id, model)
            job.map_id = pmap.id

            stage("merging")
            merge_into_project(db, db.get_one(Project, transcript.project_id), transcript, model, llm)
            stage("done")
        except Exception as e:
            log.exception("job %s failed", job_id)
            db.rollback()
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            db.commit()


async def process_transcript(ctx: dict[str, Any], job_id: str) -> None:
    # Pipeline is sync (DB + LLM calls); keep the worker's event loop free.
    await asyncio.to_thread(run_job, job_id)


async def retention(ctx: dict[str, Any]) -> int:
    return await asyncio.to_thread(purge_expired)
