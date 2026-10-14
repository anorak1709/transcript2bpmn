"""Audio -> segments. Fallback input path for when no platform transcript export exists."""

from app.core.config import Settings, get_settings
from app.pipeline.transcribe.audio import AUDIO_EXTENSIONS
from app.pipeline.transcribe.base import Transcriber, Transcription

__all__ = ["AUDIO_EXTENSIONS", "Transcriber", "Transcription", "get_transcriber"]


def get_transcriber(settings: Settings | None = None) -> Transcriber:
    """Pick the adapter named by TRANSCRIBE_PROVIDER."""
    s = settings or get_settings()
    if s.transcribe_provider in ("openai", "azure"):  # same API; Azure just needs another client
        from app.pipeline.transcribe.openai import OpenAITranscriber

        return OpenAITranscriber(s)
    if s.transcribe_provider == "deepgram":
        from app.pipeline.transcribe.deepgram import DeepgramTranscriber

        return DeepgramTranscriber(s)
    raise ValueError(f"Unknown TRANSCRIBE_PROVIDER {s.transcribe_provider!r}")
