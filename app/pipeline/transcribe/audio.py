"""ffmpeg helpers. Requires ffmpeg + ffprobe on PATH (brew install ffmpeg / apt install ffmpeg)."""

import base64
import json
import math
import subprocess
from dataclasses import dataclass
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


@dataclass
class AudioChunk:
    path: Path
    offset: float  # where the chunk's audio starts in the recording (includes leading overlap)
    duration: float
    own_start: float  # the part of the recording this chunk is responsible for...
    own_end: float | None  # ...None = to the end


def _encode(inputs: list[str], out: Path) -> None:
    """ffmpeg `inputs` -> 16 kHz mono 48 kbps MP3 at `out`."""
    opts = ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k"]
    _run(["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, *opts, str(out)])


def split(path: Path, out_dir: Path, chunk_seconds: int, overlap: float = 0.0) -> list[AudioChunk]:
    """Re-encode to 16 kHz mono 48 kbps MP3 (~3.6 MB per 10 min) and cut into chunks.

    Each chunk is responsible for [k*chunk, (k+1)*chunk) but its audio extends `overlap`
    seconds past both ends, so a word at a cut is heard whole by the chunk that owns it.
    base.stitch() keeps only each chunk's own segments, so the overlap never duplicates text.
    """
    total = duration(path)
    starts = [k * chunk_seconds for k in range(max(1, math.ceil(total / chunk_seconds)))]
    chunks = []
    for k, start in enumerate(starts):
        lo, hi = max(0.0, start - overlap), min(total, start + chunk_seconds + overlap)
        out = out_dir / f"chunk_{k:04d}.mp3"
        _encode(["-ss", f"{lo:.3f}", "-t", f"{hi - lo:.3f}", "-i", str(path)], out)
        last = k == len(starts) - 1
        chunks.append(AudioChunk(out, lo, duration(out), float(start), None if last else float(start + chunk_seconds)))
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
