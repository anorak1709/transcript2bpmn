"""Clean raw segments and assign the stable segment ids every later stage cites."""

import re

from app.models.transcript import Segment

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

    ponytail: rules only. The spec allows an LLM ("filter" role) cleanup pass; add it only
    if eval shows rule-cleaned text hurting extraction.
    """
    merged: list[Segment] = []
    for seg in raw:
        text = clean_text(seg.text)
        if not text:
            continue
        prev = merged[-1] if merged else None
        if prev and seg.speaker is not None and seg.speaker == prev.speaker:
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
