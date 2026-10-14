"""Synthesize a multi-speaker meeting recording from a transcript, with its reference.

macOS only (uses `say`); needs ffmpeg. Lines are repeated cyclically until --minutes is
reached, so a short gold transcript can become a 30+ minute test recording.

    python -m eval.asr.make_sample eval/gold/01_invoice_approval/transcript.vtt \
        --minutes 32 --out eval/asr/samples/invoice_long

Writes <out>.m4a and <out>.ref.txt ("Speaker: text" per line), the pair asr_benchmark.py reads.
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

from app.pipeline.ingest import parse

VOICES = ["Samantha", "Daniel", "Karen", "Moira", "Rishi", "Tessa"]
PAUSE_SECONDS = 0.4


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--minutes", type=float, default=1.0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    lines = parse(args.transcript.name, args.transcript.read_bytes())
    voices: dict[str, str] = {}
    ref: list[str] = []
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        silence = tmpdir / "pause.aiff"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=22050:cl=mono",
                "-t",
                str(PAUSE_SECONDS),
                str(silence),
            ],
            check=True,
        )
        parts: list[Path] = []
        total, i = 0.0, 0
        while total < args.minutes * 60:
            seg = lines[i % len(lines)]
            speaker = seg.speaker or "Narrator"
            voice = voices.setdefault(speaker, VOICES[len(voices) % len(VOICES)])
            clip = tmpdir / f"{i:05d}.aiff"
            subprocess.run(["say", "-v", voice, "-o", str(clip), seg.text], check=True)
            total += float(
                subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
            )
            total += PAUSE_SECONDS
            parts += [clip, silence]
            ref.append(f"{speaker}: {seg.text}")
            i += 1

        concat = tmpdir / "list.txt"
        concat.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-ac",
                "1",
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                str(args.out.with_suffix(".m4a")),
            ],
            check=True,
        )

    args.out.with_suffix(".ref.txt").write_text("\n".join(ref) + "\n")
    print(f"{args.out.with_suffix('.m4a')}: {total / 60:.1f} min, {i} lines, voices {voices}")


if __name__ == "__main__":
    main()
