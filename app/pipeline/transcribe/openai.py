"""OpenAI Transcriptions API adapter.

Response shape depends on the model (TRANSCRIBE_MODEL, never hardcoded):
- "*diarize*" models -> diarized_json: timed segments with speaker labels.
- "whisper*" models   -> verbose_json: timed segments, no speakers.
- anything else       -> json: text only; split into sentences with timestamps spread
                         proportionally across the chunk (approximate).
Without diarization every segment gets UNKNOWN_SPEAKER and diarization_available=False,
so the UI can ask the user to label speakers.
"""

import re
import tempfile
from pathlib import Path
from typing import Any

from openai import AzureOpenAI, OpenAI

from app.core.config import Settings, get_settings
from app.models.transcript import UNKNOWN_SPEAKER, Segment
from app.pipeline.transcribe import audio
from app.pipeline.transcribe.base import Chunk, Transcriber, Transcription, stitch

MAX_REFERENCES = 4  # API limit on known_speaker_references
REF_MIN, REF_MAX = 2.0, 10.0  # API limit on reference clip length (seconds)


class OpenAITranscriber(Transcriber):
    def __init__(self, settings: Settings | None = None, client: Any = None) -> None:
        s = settings or get_settings()
        if not s.transcribe_model:
            raise ValueError("TRANSCRIBE_MODEL is not set")
        self.model = s.transcribe_model
        self.chunk_seconds = s.transcribe_chunk_seconds
        self.diarize = "diarize" in self.model
        key = s.transcribe_api_key or s.llm_api_key
        if client is not None:
            self.client = client
        elif s.transcribe_provider == "azure":  # TRANSCRIBE_MODEL is the Azure deployment name
            self.client = AzureOpenAI(
                api_key=key,
                azure_endpoint=s.transcribe_api_base or s.llm_api_base or "",
                api_version=s.transcribe_api_version or s.llm_api_version,
            )
        else:
            self.client = OpenAI(api_key=key, base_url=s.transcribe_api_base or None)

    def transcribe(self, audio_path: Path) -> Transcription:
        chunks: list[Chunk] = []
        names: list[str] = []
        refs: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            for i, (path, offset, length) in enumerate(audio.split(audio_path, Path(tmp), self.chunk_seconds)):
                segments = self._transcribe_chunk(path, length, i, names, refs)
                if self.diarize and i == 0:
                    # Labels restart at "A" on every request; anchoring later chunks to voice
                    # samples from the first keeps "Speaker A" the same person all meeting.
                    names, refs = _speaker_references(path, segments)
                chunks.append(Chunk(offset=offset, duration=length, segments=segments))
        return Transcription(segments=stitch(chunks), diarization_available=self.diarize)

    def _transcribe_chunk(
        self, path: Path, length: float, index: int, names: list[str], refs: list[str]
    ) -> list[Segment]:
        kwargs: dict[str, Any] = {"model": self.model}
        if self.diarize:
            kwargs |= {"response_format": "diarized_json", "chunking_strategy": "auto"}
            if names:
                kwargs |= {"known_speaker_names": names, "known_speaker_references": refs}
        elif self.model.startswith("whisper"):
            kwargs |= {"response_format": "verbose_json", "timestamp_granularities": ["segment"]}
        else:
            kwargs["response_format"] = "json"

        with path.open("rb") as f:
            data = self.client.audio.transcriptions.create(file=f, **kwargs).model_dump()

        if self.diarize:
            return [
                _seg(_speaker_label(s.get("speaker"), names, index), s["start"], s["end"], s["text"])
                for s in data.get("segments") or []
            ]
        if data.get("segments"):
            return [_seg(UNKNOWN_SPEAKER, s["start"], s["end"], s["text"]) for s in data["segments"]]
        return _sentences(data.get("text") or "", length)


def _seg(speaker: str, start: float, end: float, text: str) -> Segment:
    return Segment(segment_id="", speaker=speaker, start_ts=start, end_ts=end, text=text.strip())


def _speaker_label(raw: str | None, known: list[str], chunk_index: int) -> str:
    if not raw:
        return UNKNOWN_SPEAKER
    if raw in known:
        return raw
    if chunk_index == 0:
        return f"Speaker {raw}"
    # A voice not among the references: can't be matched to an earlier label, so keep it
    # distinct rather than risk merging two people.
    return f"Speaker {raw} (part {chunk_index + 1})"


def _speaker_references(path: Path, segments: list[Segment]) -> tuple[list[str], list[str]]:
    """Pick one 2-10 s clip per speaker (longest available) from the first chunk."""
    best: dict[str, Segment] = {}
    for seg in segments:
        length = (seg.end_ts or 0) - (seg.start_ts or 0)
        if seg.speaker == UNKNOWN_SPEAKER or length < REF_MIN:
            continue
        cur = best.get(seg.speaker or "")
        if cur is None or length > (cur.end_ts or 0) - (cur.start_ts or 0):
            best[seg.speaker or ""] = seg
    names, refs = [], []
    for name, seg in list(best.items())[:MAX_REFERENCES]:
        start = seg.start_ts or 0
        names.append(name)
        refs.append(audio.clip_data_url(path, start, min((seg.end_ts or 0) - start, REF_MAX)))
    return names, refs


def _sentences(text: str, length: float) -> list[Segment]:
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p]
    total = sum(len(p) for p in parts) or 1
    out, pos = [], 0
    for p in parts:
        start = length * pos / total
        pos += len(p)
        out.append(_seg(UNKNOWN_SPEAKER, start, length * pos / total, p))
    return out
