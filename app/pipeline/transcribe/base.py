from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from app.models.transcript import Segment


@dataclass
class Transcription:
    segments: list[Segment]  # same schema the text parsers produce; normalize() runs next
    diarization_available: bool


class Transcriber(ABC):
    """One adapter per ASR provider. Adding a provider never touches the pipeline."""

    @abstractmethod
    def transcribe(self, audio_path: Path) -> Transcription: ...


@dataclass
class Chunk:
    offset: float  # seconds into the original recording
    duration: float
    segments: list[Segment] = field(default_factory=list)  # timestamps relative to the chunk


def stitch(chunks: list[Chunk]) -> list[Segment]:
    """Shift chunk-relative timestamps onto the recording timeline.

    Guarantees monotonic, in-bounds output even when a provider returns timestamps slightly
    past the chunk end or out of order: each segment is clamped into its chunk's window and
    never starts before the previous one.
    """
    out: list[Segment] = []
    last = 0.0
    for chunk in sorted(chunks, key=lambda c: c.offset):
        hi = chunk.offset + chunk.duration
        for seg in chunk.segments:
            start = min(max(chunk.offset + (seg.start_ts or 0.0), last, chunk.offset), hi)
            end = min(max(chunk.offset + (seg.end_ts or 0.0), start), hi)
            out.append(seg.model_copy(update={"segment_id": f"raw{len(out)}", "start_ts": start, "end_ts": end}))
            last = start
    return out
