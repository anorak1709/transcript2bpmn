import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from app import storage
from app.db.base import SessionLocal
from app.db.models import Job, ProcessMap, Transcript
from app.llm.provider import LiteLLMProvider, LLMProvider
from app.pipeline import extract, ingest, normalize
from app.pipeline.run import model_to_bpmn
from app.pipeline.transcribe import AUDIO_EXTENSIONS, Transcriber, get_transcriber

log = logging.getLogger(__name__)


def run_job(job_id: str, llm: LLMProvider | None = None, transcriber: Transcriber | None = None) -> None:
    """Run the full pipeline for one job, recording each stage on the Job row."""
    with SessionLocal() as db:
        job = db.get_one(Job, job_id)
        transcript = db.get_one(Transcript, job.transcript_id)

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
            segments = normalize.normalize(raw)
            transcript.segments = [s.model_dump() for s in segments]

            stage("extracting")
            model = extract.extract(llm or LiteLLMProvider(), segments)

            stage("converting")
            pmap = ProcessMap(transcript_id=transcript.id, model=model.model_dump(), bpmn_xml=model_to_bpmn(model))
            db.add(pmap)
            db.flush()
            job.map_id = pmap.id
            stage("done")
        except Exception as e:
            log.exception("job %s failed", job_id)
            db.rollback()
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            db.commit()


async def process_transcript(ctx: dict[str, Any], job_id: str) -> None:
    # Pipeline is sync (DB + LLM calls); keep the worker's event loop free.
    await asyncio.to_thread(run_job, job_id)
