"""Compare ASR providers/models: WER and speaker-attribution accuracy per file.

Input folder: audio files (.mp3/.m4a/.wav/.webm/.mp4), each with a `<stem>.ref.txt`
reference in "Speaker: text" lines (eval/asr/make_sample.py writes these pairs).

    python -m eval.asr_benchmark eval/asr/samples                       # env TRANSCRIBE_* config
    python -m eval.asr_benchmark eval/asr/samples \
        --configs openai:gpt-4o-transcribe-diarize openai:gpt-transcribe   # provider[:model] each

Speaker accuracy: hypothesis words are aligned to reference words; each hypothesis label
("Speaker A") is mapped to the reference speaker it overlaps most, then we count aligned
words whose mapped speaker is right. n/a when the provider gave no speaker labels.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.models.transcript import UNKNOWN_SPEAKER, Segment
from app.pipeline.ingest import parse
from app.pipeline.transcribe import AUDIO_EXTENSIONS, get_transcriber


def words(segments: list[Segment]) -> list[tuple[str, str]]:
    """(word, speaker) pairs; lowercase, punctuation stripped (apostrophes kept)."""
    return [
        (w, seg.speaker or UNKNOWN_SPEAKER)
        for seg in segments
        for w in re.sub(r"[^\w\s']", " ", seg.text.lower()).split()
    ]


def wer(ref: list[str], hyp: list[str]) -> float:
    """Word error rate: word-level Levenshtein distance / reference length."""
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def speaker_accuracy(ref: list[tuple[str, str]], hyp: list[tuple[str, str]]) -> float | None:
    if all(s == UNKNOWN_SPEAKER for _, s in hyp):
        return None
    sm = SequenceMatcher(None, [w for w, _ in ref], [w for w, _ in hyp], autojunk=False)
    pairs = [(ref[b.a + k][1], hyp[b.b + k][1]) for b in sm.get_matching_blocks() for k in range(b.size)]
    if not pairs:
        return 0.0
    overlap: dict[str, Counter[str]] = defaultdict(Counter)
    for r, h in pairs:
        overlap[h][r] += 1
    mapping = {h: c.most_common(1)[0][0] for h, c in overlap.items()}
    return sum(mapping[h] == r for r, h in pairs) / len(pairs)


def run(folder: Path, configs: list[str]) -> dict[str, Any]:
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS)
    rows = []
    for cfg in configs:
        provider, _, model = cfg.partition(":")
        settings = get_settings().model_copy(
            update={"transcribe_provider": provider} | ({"transcribe_model": model} if model else {})
        )
        label = f"{provider}:{settings.transcribe_model}"
        for audio in files:
            ref_path = audio.with_name(audio.stem + ".ref.txt")
            row: dict[str, Any] = {"config": label, "file": audio.name}
            try:
                ref = words(parse(ref_path.name, ref_path.read_bytes()))
                hyp = words(get_transcriber(settings).transcribe(audio).segments)
                row |= {
                    "wer": wer([w for w, _ in ref], [w for w, _ in hyp]),
                    "speaker_accuracy": speaker_accuracy(ref, hyp),
                }
            except Exception as e:  # one provider failing must not hide the others' results
                row["error"] = f"{type(e).__name__}: {e}"
            rows.append(row)
    return {"rows": rows}


def to_markdown(results: dict[str, Any]) -> str:
    out = ["# ASR benchmark", "", "| config | file | WER | speaker accuracy |", "|---|---|---|---|"]
    for r in results["rows"]:
        if "error" in r:
            out.append(f"| {r['config']} | {r['file']} | ERROR: {r['error'][:120]} | |")
        else:
            spk = "n/a" if r["speaker_accuracy"] is None else f"{r['speaker_accuracy']:.1%}"
            out.append(f"| {r['config']} | {r['file']} | {r['wer']:.1%} | {spk} |")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--configs", nargs="+", default=None, help="provider[:model] (default: env TRANSCRIBE_*)")
    ap.add_argument("--out", type=Path, default=Path("eval/reports/asr"))
    args = ap.parse_args()

    s = get_settings()
    results = run(args.folder, args.configs or [f"{s.transcribe_provider}:{s.transcribe_model}"])
    args.out.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("%Y%m%d-%H%M%S")
    (args.out / f"{stem}.json").write_text(json.dumps(results, indent=2))
    md = to_markdown(results)
    (args.out / f"{stem}.md").write_text(md)
    print(md + f"\nReport: {args.out / stem}.md")


if __name__ == "__main__":
    main()
