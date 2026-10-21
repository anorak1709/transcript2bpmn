"""Live interviews: the browser records and sends one complete audio chunk every few minutes
(LIVE_CHUNK_SECONDS); each is transcribed, appended to the running transcript, and the draft
map is re-extracted from everything so far. Finishing merges it into the process like any
meeting. Every chunk costs transcription + extraction credits, so demo mode refuses it.
"""

import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import maps, storage
from app.db.models import ProcessMap, Transcript
from app.db.tenancy import bind, system_session
from app.llm.provider import LiteLLMProvider, LLMProvider
from app.models.transcript import Segment
from app.pipeline.run import model_from_segments, prepare_segments
from app.pipeline.transcribe import Transcriber, get_transcriber


def chunk_key(t: Transcript, index: int) -> str:
    return f"{t.storage_key.rsplit('/', 1)[0]}/chunks/{index:04d}.webm"


def transcript_map(db: Session, transcript_id: str) -> ProcessMap | None:
    """A meeting's own map (live interviews and re-processing keep updating the same one)."""
    return db.scalars(
        select(ProcessMap).where(ProcessMap.transcript_id == transcript_id).order_by(ProcessMap.created_at)
    ).first()


def process_chunk(
    transcript_id: str,
    index: int,
    offset_s: float,
    llm: LLMProvider | None = None,
    transcriber: Transcriber | None = None,
) -> int:
    """Transcribe chunk `index` (which started `offset_s` seconds into the interview), append its
    lines, and redraw the draft map. Chunks of one interview are serialised by a row lock, so
    lines always arrive in order. Returns the number of lines added."""
    with system_session() as db:
        org_id = db.get_one(Transcript, transcript_id).organization_id
        bind(db, org_id)
        t = db.get_one(Transcript, transcript_id, with_for_update=True, populate_existing=True)
        if t.live_status != "recording":
            return 0
        llm = llm or LiteLLMProvider()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chunk.webm"
            storage.download(chunk_key(t, index), path)
            result = (transcriber or get_transcriber()).transcribe(path)
        lines = prepare_segments(result.segments, llm)
        existing = [Segment.model_validate(s) for s in t.segments or []]
        start = len(existing)
        added = [
            s.model_copy(
                update={
                    "segment_id": f"s{start + i}",
                    "start_ts": None if s.start_ts is None else s.start_ts + offset_s,
                    "end_ts": None if s.end_ts is None else s.end_ts + offset_s,
                }
            )
            for i, s in enumerate(lines, 1)
        ]
        everything = existing + added
        t.segments = [s.model_dump() for s in everything]
        t.diarization_available = result.diarization_available
        if everything:
            model = model_from_segments(everything, llm).model
            pmap = transcript_map(db, t.id)
            if pmap is None:
                maps.create_map(db, t.project_id, t.id, model)
            else:
                maps.commit_version(db, pmap, model, "extract", maps.current_positions(pmap))
        db.commit()
        return len(added)
