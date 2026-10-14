"""Deepgram adapter: documented stub, not implemented.

How to add a second ASR provider (Deepgram, AssemblyAI, ...) without touching the pipeline:

1. Subclass `Transcriber` and implement `transcribe(audio_path) -> Transcription`.
   - Return `Segment`s with `speaker`, `start_ts`/`end_ts` in seconds on the recording's
     timeline, and `text`. `segment_id` can be anything; normalize() reassigns ids.
   - Deepgram's pre-recorded API accepts large files directly (diarize=true, utterances=true
     gives speaker-labelled utterances), so chunking is probably unnecessary. If you do chunk,
     reuse `audio.split()` + `base.stitch()` like the OpenAI adapter.
   - Set `diarization_available` to whether the provider returned real speaker labels.
2. Read credentials and model from Settings (add e.g. DEEPGRAM_API_KEY; model from TRANSCRIBE_MODEL).
3. Register it in `get_transcriber()` under its TRANSCRIBE_PROVIDER name (already done for "deepgram").
4. Compare it against the current provider with `eval/asr_benchmark.py --providers openai deepgram`.
"""

from pathlib import Path

from app.core.config import Settings
from app.pipeline.transcribe.base import Transcriber, Transcription


class DeepgramTranscriber(Transcriber):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def transcribe(self, audio_path: Path) -> Transcription:
        raise NotImplementedError("Deepgram adapter is a stub; see module docstring")
