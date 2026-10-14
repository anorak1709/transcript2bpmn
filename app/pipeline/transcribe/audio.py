"""ffmpeg helpers. Requires ffmpeg + ffprobe on PATH (brew install ffmpeg / apt install ffmpeg)."""

import base64
import json
import subprocess
from pathlib import Path

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".webm", ".mp4")


class AudioError(ValueError):
    pass


def _run(args: list[str]) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=True)
    except FileNotFoundError as e:
        raise AudioError(f"{args[0]} not found; install ffmpeg") from e
    except subprocess.CalledProcessError as e:
        raise AudioError(f"{args[0]} failed: {e.stderr.strip()[-500:]}") from e
    return proc.stdout


def duration(path: Path) -> float:
    """Seconds of audio. Raises AudioError if the file has no decodable audio stream."""
    out = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type:format=duration",
            "-of",
            "json",
            str(path),
        ]
    )
    info = json.loads(out)
    if not info.get("streams"):
        raise AudioError("No audio stream found")
    return float(info["format"]["duration"])


def split(path: Path, out_dir: Path, chunk_seconds: int) -> list[tuple[Path, float, float]]:
    """Re-encode to 16 kHz mono 48 kbps MP3 (~3.6 MB per 10 min) and split into chunks.

    Returns [(chunk_path, offset_seconds, duration_seconds)]. Offsets come from each chunk's measured
    duration, not chunk_seconds, so they stay correct when ffmpeg cuts on frame boundaries.
    ponytail: hard cuts can split a word at a boundary; add overlap + dedupe if WER at
    chunk edges shows up in the ASR benchmark.
    """
    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "48k",
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-reset_timestamps",
            "1",
            str(out_dir / "chunk_%04d.mp3"),
        ]
    )
    chunks, offset = [], 0.0
    for p in sorted(out_dir.glob("chunk_*.mp3")):
        d = duration(p)
        chunks.append((p, offset, d))
        offset += d
    return chunks


def clip_data_url(path: Path, start: float, length: float) -> str:
    """A short WAV clip as a data URL (for providers that accept speaker reference samples)."""
    wav = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{length:.3f}",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return "data:audio/wav;base64," + base64.b64encode(wav).decode()
