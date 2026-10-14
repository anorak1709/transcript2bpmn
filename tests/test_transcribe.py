import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.models.transcript import UNKNOWN_SPEAKER, Segment
from app.pipeline.normalize import normalize
from app.pipeline.transcribe import audio, get_transcriber
from app.pipeline.transcribe.base import Chunk, stitch
from app.pipeline.transcribe.openai import OpenAITranscriber
from eval.asr_benchmark import speaker_accuracy, wer, words

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _seg(start: float, end: float, text: str = "x", speaker: str = "A") -> Segment:
    return Segment(segment_id="", speaker=speaker, start_ts=start, end_ts=end, text=text)


def test_stitch_offsets_and_keeps_timestamps_monotonic() -> None:
    chunks = [
        Chunk(offset=600.0, duration=300.0, segments=[_seg(0, 4), _seg(2, 3), _seg(299, 305)]),  # out of order, overrun
        Chunk(offset=0.0, duration=600.0, segments=[_seg(1, 5), _seg(590, 601)]),  # listed second, overruns
        Chunk(offset=900.0, duration=60.0, segments=[_seg(-5, 2)]),  # negative start from provider
    ]
    out = stitch(chunks)
    starts = [s.start_ts or 0 for s in out]
    assert starts == sorted(starts)
    assert [(s.start_ts, s.end_ts) for s in out] == [
        (1.0, 5.0),
        (590.0, 600.0),  # clamped to its chunk's end
        (600.0, 604.0),  # shifted by offset
        (602.0, 603.0),  # starts after the previous start: overlap allowed, order kept
        (899.0, 900.0),  # clamped to its chunk's end
        (900.0, 902.0),  # clamped to its chunk's start
    ]
    assert [s.segment_id for s in out] == [f"raw{i}" for i in range(6)]
    assert all((s.end_ts or 0) >= (s.start_ts or 0) for s in out)


@pytest.fixture
def tone(tmp_path: Path) -> Path:
    """25 s of audio (two tones so it isn't trivially compressible)."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    path = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:d=12",
            "-f",
            "lavfi",
            "-i",
            "sine=f=660:d=13",
            "-filter_complex",
            "[0][1]concat=n=2:v=0:a=1",
            str(path),
        ],
        check=True,
    )
    return path


@needs_ffmpeg
def test_split_measures_real_offsets(tone: Path, tmp_path: Path) -> None:
    out = tmp_path / "chunks"
    out.mkdir()
    chunks = audio.split(tone, out, chunk_seconds=10)
    assert len(chunks) == 3
    offsets = [o for _, o, _ in chunks]
    assert offsets[0] == 0 and abs(offsets[1] - 10) < 0.2 and abs(offsets[2] - 20) < 0.2
    assert abs(sum(d for _, _, d in chunks) - 25) < 0.2
    assert abs(audio.duration(tone) - 25) < 0.1


def test_duration_rejects_non_audio(tmp_path: Path) -> None:
    if shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg not installed")
    bad = tmp_path / "x.mp3"
    bad.write_text("not audio")
    with pytest.raises(audio.AudioError):
        audio.duration(bad)


class FakeClient:
    """Stands in for openai.OpenAI: records each create() call and replays scripted responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.audio = self
        self.transcriptions = self

    def create(self, file: Any, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        data = self.responses[len(self.calls) - 1]
        return type("Resp", (), {"model_dump": lambda self: data})()


def _settings(model: str, **kw: Any) -> Settings:
    return Settings(_env_file=None, transcribe_model=model, transcribe_chunk_seconds=10, **kw)


def _diarized(*segs: tuple[str, float, float, str]) -> dict[str, Any]:
    return {"segments": [{"speaker": s, "start": a, "end": b, "text": t} for s, a, b, t in segs]}


@needs_ffmpeg
def test_diarized_chunks_keep_speakers_consistent(tone: Path) -> None:
    client = FakeClient(
        [
            _diarized(("A", 0.0, 4.0, "We enter the invoice."), ("B", 4.5, 9.5, "Then finance approves it.")),
            _diarized(("Speaker A", 0.5, 3.0, "Matched."), ("C", 3.0, 6.0, "New voice here.")),
            _diarized(("Speaker B", 1.0, 2.0, "Paid.")),
        ]
    )
    result = OpenAITranscriber(_settings("gpt-4o-transcribe-diarize"), client).transcribe(tone)

    assert result.diarization_available is True
    assert client.calls[0]["response_format"] == "diarized_json"
    assert client.calls[0]["chunking_strategy"] == "auto"
    assert "known_speaker_names" not in client.calls[0]
    # Later chunks are anchored to voice samples of the first chunk's speakers.
    assert client.calls[1]["known_speaker_names"] == ["Speaker A", "Speaker B"]
    assert all(r.startswith("data:audio/wav;base64,") for r in client.calls[1]["known_speaker_references"])

    assert [s.speaker for s in result.segments] == [
        "Speaker A",
        "Speaker B",
        "Speaker A",
        "Speaker C (part 2)",  # unmatched voice stays distinct
        "Speaker B",
    ]
    starts = [s.start_ts or 0 for s in result.segments]
    assert starts == sorted(starts)
    assert abs(starts[2] - 10.5) < 0.2 and abs(starts[4] - 21.0) < 0.2  # chunk offsets applied


@needs_ffmpeg
def test_text_only_model_falls_back_to_unknown_speaker(tone: Path) -> None:
    client = FakeClient([{"text": "First we check it. Then we pay."}] + [{"text": ""}] * 2)
    result = OpenAITranscriber(_settings("gpt-transcribe"), client).transcribe(tone)
    assert result.diarization_available is False
    assert client.calls[0]["response_format"] == "json"
    assert [(s.speaker, s.text) for s in result.segments] == [
        (UNKNOWN_SPEAKER, "First we check it."),
        (UNKNOWN_SPEAKER, "Then we pay."),
    ]
    # Unknown speakers are never merged, so citations stay sentence-sized.
    assert len(normalize(result.segments)) == 2


@needs_ffmpeg
def test_transcribe_model_comes_from_env(tone: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for model in ("whisper-1", "some-future-transcribe-model"):
        monkeypatch.setenv("TRANSCRIBE_MODEL", model)
        monkeypatch.setenv("TRANSCRIBE_CHUNK_SECONDS", "30")
        client = FakeClient([{"segments": [{"start": 0, "end": 1, "text": "hi"}]}])
        OpenAITranscriber(Settings(_env_file=None), client).transcribe(tone)
        assert client.calls[0]["model"] == model


def test_missing_model_and_unknown_provider_fail_loudly() -> None:
    with pytest.raises(ValueError, match="TRANSCRIBE_MODEL"):
        get_transcriber(_settings(""))
    with pytest.raises(ValueError, match="TRANSCRIBE_PROVIDER"):
        get_transcriber(_settings("m", transcribe_provider="nope"))
    with pytest.raises(NotImplementedError):
        get_transcriber(_settings("m", transcribe_provider="deepgram")).transcribe(Path("x.wav"))


def test_wer() -> None:
    assert wer(["the", "cat", "sat"], ["the", "cat", "sat"]) == 0
    assert wer(["the", "cat", "sat"], ["the", "bat", "sat", "down"]) == 2 / 3  # 1 sub + 1 ins
    assert wer([], []) == 0


def test_speaker_accuracy_maps_labels_by_overlap() -> None:
    ref = words([_seg(0, 1, "we enter the invoice", "Priya"), _seg(1, 2, "then I approve it", "Marco")])
    hyp = words([_seg(0, 1, "we enter the invoice then", "Speaker B"), _seg(1, 2, "I approve it", "Speaker A")])
    # B->Priya, A->Marco by overlap; only "then" is attributed to the wrong person.
    assert speaker_accuracy(ref, hyp) == pytest.approx(7 / 8)
    assert speaker_accuracy(ref, words([_seg(0, 1, "we enter", UNKNOWN_SPEAKER)])) is None
