"""Clean raw segments and assign the stable segment ids every later stage cites."""

import logging
import re

from pydantic import BaseModel

from app.llm.provider import LLMProvider
from app.models.transcript import UNKNOWN_SPEAKER, Segment
from app.pipeline.prompts import load_prompt

# Pure fillers, removed anywhere. "you know" only when set off as a filler (", you know,"
# or sentence-initial "You know,"), so "do you know the code" survives.
_FILLERS = re.compile(r"(?:,\s*)?\b(?:um+|uh+|uhm+|erm+|hmm+)\b,?", re.IGNORECASE)
_YOU_KNOW = re.compile(r"(?:,\s*you know\b,?|(?:^|(?<=[.!?]\s))you know,\s*)", re.IGNORECASE)


def clean_text(text: str) -> str:
    text = _YOU_KNOW.sub("", text)
    text = _FILLERS.sub("", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)  # "word ," -> "word,"
    text = re.sub(r",(?=[,.!?])", "", text)  # ",." -> "."
    text = text.strip(" ,")
    if not any(ch.isalnum() for ch in text):
        return ""
    return text[:1].upper() + text[1:]


def normalize(raw: list[Segment]) -> list[Segment]:
    """Strip fillers, drop empties, merge consecutive same-speaker fragments, number s1..sN.

    Rules only; see llm_cleanup() for the optional model pass (NORMALIZE_LLM_CLEANUP).
    """
    merged: list[Segment] = []
    for seg in raw:
        text = clean_text(seg.text)
        if not text:
            continue
        prev = merged[-1] if merged else None
        # Unknown speakers are never merged: one undiarized recording would collapse into a
        # single giant segment and citations would become useless.
        if prev and seg.speaker not in (None, UNKNOWN_SPEAKER) and seg.speaker == prev.speaker:
            prev.text = f"{prev.text} {text}"
            prev.end_ts = seg.end_ts if seg.end_ts is not None else prev.end_ts
        else:
            merged.append(seg.model_copy(update={"text": text}))
    for i, seg in enumerate(merged, 1):
        seg.segment_id = f"s{i}"
    return merged


def render(segments: list[Segment]) -> str:
    """The form the LLM sees: one line per segment, id first so it can be cited."""
    return "\n".join(f"[{s.segment_id}] {s.speaker or 'Unknown'}: {s.text}" for s in segments)


CLEANUP_PROMPT = "cleanup_v1"
CLEANUP_BATCH_CHARS = 8_000
log = logging.getLogger(__name__)


class CleanSegment(BaseModel):
    segment_id: str
    text: str


class CleanBatch(BaseModel):
    segments: list[CleanSegment]


def llm_cleanup(llm: LLMProvider, segments: list[Segment]) -> list[Segment]:
    """Optional model pass ("filter" role) after the rules, mainly for ASR output: fixes
    misrecognitions, false starts and repetitions. Segment ids never change. A rewrite is
    rejected (original kept) if it's empty or much longer than the original, since
    that's a model adding content, not cleaning it."""
    cleaned: dict[str, str] = {}
    batch: list[Segment] = []

    def flush() -> None:
        if not batch:
            return
        ids = {s.segment_id for s in batch}
        result = llm.structured(load_prompt(CLEANUP_PROMPT), render(batch), CleanBatch, "filter")
        cleaned.update({c.segment_id: c.text.strip() for c in result.segments if c.segment_id in ids})
        batch.clear()

    for seg in segments:
        if batch and sum(len(s.text) for s in batch) + len(seg.text) > CLEANUP_BATCH_CHARS:
            flush()
        batch.append(seg)
    flush()

    out, rejected = [], 0
    for seg in segments:
        new = cleaned.get(seg.segment_id)
        if new is None:
            out.append(seg)
        elif not new:
            continue  # model says it was pure filler
        elif len(new) > 1.3 * len(seg.text) + 20:
            rejected += 1
            out.append(seg)
        else:
            out.append(seg.model_copy(update={"text": new}))
    if rejected:
        log.warning("llm cleanup: kept original text for %d segment(s) the model expanded", rejected)
    return out
