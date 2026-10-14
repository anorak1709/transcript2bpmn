"""Parse uploaded transcript files into raw (un-normalized) segments."""

import io
import re
from collections.abc import Iterable
from pathlib import Path

import docx
import webvtt  # type: ignore[import-untyped]

from app.models.transcript import Segment

SUPPORTED = (".vtt", ".srt", ".txt", ".docx")

# "Priya: text" / "Dr. Marco Rossi: text". Short names only, so "Note: the PO..." mid-prose
# lines are the main false positive; acceptable for transcripts.
_SPEAKER_LINE = re.compile(r"^\s*([A-Z][\w.'\- ]{0,40}?)\s*:\s+(\S.*)$")


class UnsupportedFile(ValueError):
    pass


def parse(filename: str, data: bytes) -> list[Segment]:
    ext = Path(filename).suffix.lower()
    if ext in (".vtt", ".srt"):
        return _parse_captions(data, ext[1:])
    if ext == ".txt":
        return _parse_lines(data.decode("utf-8-sig", errors="replace").splitlines())
    if ext == ".docx":
        return _parse_lines(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    raise UnsupportedFile(f"Unsupported file type {ext!r}; expected one of {', '.join(SUPPORTED)}")


def _seconds(ts: str) -> float:
    parts = [float(p) for p in ts.replace(",", ".").split(":")]
    return float(sum(p * 60**i for i, p in enumerate(reversed(parts))))


def _parse_captions(data: bytes, fmt: str) -> list[Segment]:
    try:
        captions = webvtt.from_buffer(io.BytesIO(data), format=fmt).captions
    except Exception as e:  # webvtt raises several error types for malformed files
        raise UnsupportedFile(f"Could not parse {fmt.upper()}: {e}") from e
    out = []
    for i, c in enumerate(captions):
        text = " ".join(c.text.split())
        speaker = c.voice
        if speaker is None and (m := _SPEAKER_LINE.match(text)):
            speaker, text = m.group(1), m.group(2)
        start, end = _seconds(c.start), _seconds(c.end)
        out.append(Segment(segment_id=f"raw{i}", speaker=speaker, start_ts=start, end_ts=end, text=text))
    return out


def _parse_lines(lines: Iterable[str]) -> list[Segment]:
    out: list[Segment] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        speaker, text = None, line
        if m := _SPEAKER_LINE.match(line):
            speaker, text = m.group(1), m.group(2)
        out.append(Segment(segment_id=f"raw{len(out)}", speaker=speaker, start_ts=None, end_ts=None, text=text))
    return out
