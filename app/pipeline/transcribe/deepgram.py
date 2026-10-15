"""Deepgram adapter (pre-recorded API).

One request per recording: Deepgram accepts up to 2 GB, so there's no chunking and speaker
numbers stay consistent across the whole meeting (unlike per-chunk labels). The audio is
re-encoded to 16 kHz mono MP3 first, which turns an hour of WAV (~600 MB) into ~22 MB.

Config: TRANSCRIBE_PROVIDER=deepgram, TRANSCRIBE_MODEL (e.g. nova-3), DEEPGRAM_API_KEY.
"""

import tempfile
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.models.transcript import UNKNOWN_SPEAKER, Segment
from app.pipeline.transcribe import audio
from app.pipeline.transcribe.base import Transcriber, Transcription

TIMEOUT_S = 660  # Deepgram gives up on Nova requests after 10 minutes server-side


class DeepgramTranscriber(Transcriber):
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.transcribe_model:
            raise ValueError("TRANSCRIBE_MODEL is not set (e.g. nova-3)")
        if not settings.deepgram_api_key and client is None:
            raise ValueError("DEEPGRAM_API_KEY is not set")
        self.model = settings.transcribe_model
        self.diarize = settings.deepgram_diarize
        self.client = client or httpx.Client(
            base_url=settings.deepgram_api_base,
            headers={"Authorization": f"Token {settings.deepgram_api_key}"},
            timeout=TIMEOUT_S,
        )

    def transcribe(self, audio_path: Path) -> Transcription:
        params = {
            "model": self.model,
            "language": "en",
            "smart_format": "true",
            "punctuate": "true",
            "utterances": "true",
            "diarize": str(self.diarize).lower(),
        }
        with tempfile.TemporaryDirectory() as tmp:
            mp3 = Path(tmp) / "audio.mp3"
            audio.encode_mp3(audio_path, mp3)
            with mp3.open("rb") as f:
                r = self.client.post("/v1/listen", params=params, content=f, headers={"Content-Type": "audio/mpeg"})
        if r.status_code >= 400:
            raise RuntimeError(f"Deepgram {r.status_code}: {r.text[:300]}")
        return parse_response(r.json(), self.diarize)


def parse_response(data: dict[str, Any], diarize: bool) -> Transcription:
    utterances = data.get("results", {}).get("utterances") or []
    segments = [
        Segment(
            segment_id="",
            speaker=f"Speaker {u['speaker'] + 1}" if diarize and u.get("speaker") is not None else UNKNOWN_SPEAKER,
            start_ts=float(u["start"]),
            end_ts=float(u["end"]),
            text=u["transcript"].strip(),
        )
        for u in utterances
        if u.get("transcript", "").strip()
    ]
    if not segments:  # no utterances (very short audio): fall back to the plain transcript
        alt = (data.get("results", {}).get("channels") or [{}])[0].get("alternatives") or [{}]
        text = (alt[0].get("transcript") or "").strip()
        if text:
            segments = [Segment(segment_id="", speaker=UNKNOWN_SPEAKER, start_ts=0.0, end_ts=None, text=text)]
    has_speakers = any(s.speaker != UNKNOWN_SPEAKER for s in segments)
    return Transcription(
        segments=[s.model_copy(update={"segment_id": f"raw{i}"}) for i, s in enumerate(segments)],
        diarization_available=has_speakers,
    )
