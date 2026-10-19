"""Two-pass extraction: relevance filter, then structured ProcessModel extraction."""

import logging

from pydantic import BaseModel

from app.core.config import get_settings
from app.llm.provider import LLMProvider
from app.models.process import Node, OpenQuestion, ProcessModel
from app.models.transcript import Segment
from app.pipeline.merge import merge
from app.pipeline.normalize import render
from app.pipeline.prompts import load_prompt

log = logging.getLogger(__name__)

FILTER_PROMPT = "filter_v1"
EXTRACT_PROMPT = "extract_v2"
BATCH_CHARS = 12_000  # ~3k tokens of transcript per filter call


class RelevanceLabel(BaseModel):
    segment_id: str
    process_relevant: bool
    reason: str


class RelevanceBatch(BaseModel):
    labels: list[RelevanceLabel]


def batches(segments: list[Segment], max_chars: int = BATCH_CHARS) -> list[list[Segment]]:
    out: list[list[Segment]] = [[]]
    size = 0
    for seg in segments:
        if out[-1] and size + len(seg.text) > max_chars:
            out.append([])
            size = 0
        out[-1].append(seg)
        size += len(seg.text)
    return [b for b in out if b]


def filter_relevant(llm: LLMProvider, segments: list[Segment]) -> list[Segment]:
    prompt = load_prompt(FILTER_PROMPT)
    irrelevant: set[str] = set()
    for batch in batches(segments):
        result = llm.structured(prompt, render(batch), RelevanceBatch, "filter")
        irrelevant |= {lbl.segment_id for lbl in result.labels if not lbl.process_relevant}
    # Unlabelled segments are kept: dropping a real step costs more than keeping noise.
    return [s for s in segments if s.segment_id not in irrelevant]


WINDOW_OVERLAP = 3  # segments repeated at each window edge, so a step spanning the cut is seen whole


def extract_model(llm: LLMProvider, segments: list[Segment]) -> ProcessModel:
    """One extraction call if the transcript fits EXTRACT_MAX_CHARS; otherwise extract
    overlapping windows and fold them together with the multi-meeting merge, which matches
    the same step seen in two windows instead of duplicating it."""
    windows = extraction_windows(segments, get_settings().extract_max_chars)
    model = _extract_one(llm, windows[0])
    for k, window in enumerate(windows[1:], 2):
        model = merge(llm, model, _extract_one(llm, window), f"part {k} of this meeting").model
    if len(windows) > 1:
        log.info("extracted %d windows of %d segments", len(windows), len(segments))
    return model


def _extract_one(llm: LLMProvider, segments: list[Segment]) -> ProcessModel:
    model = llm.structured(load_prompt(EXTRACT_PROMPT), render(segments), ProcessModel, "extract")
    return enforce_citations(model, {s.segment_id for s in segments})


def extraction_windows(segments: list[Segment], max_chars: int) -> list[list[Segment]]:
    """Consecutive windows of at most ~max_chars of text, each starting with the last
    WINDOW_OVERLAP segments of the previous one."""
    windows: list[list[Segment]] = []
    start = 0
    while start < len(segments):
        size, end = 0, start
        while end < len(segments) and (end == start or size + len(segments[end].text) <= max_chars):
            size += len(segments[end].text)
            end += 1
        windows.append(segments[start:end])
        if end >= len(segments):
            break
        start = max(end - WINDOW_OVERLAP, start + 1)
    return windows or [[]]


def enforce_citations(model: ProcessModel, valid_ids: set[str]) -> ProcessModel:
    """Guarantee every node cites >=1 real segment.

    Invented ids are dropped. A node left with none borrows its flow neighbours' citations
    (confidence halved, so the UI can flag it); if the whole graph is uncited, the first
    valid segment is used.
    """
    items: list[Node | OpenQuestion] = [*model.nodes, *model.open_questions]
    for item in items:
        bad = [i for i in item.source_segment_ids if i not in valid_ids]
        if bad:
            log.warning("dropping invented segment ids %s on %s", bad, item.id)
            item.source_segment_ids = [i for i in item.source_segment_ids if i in valid_ids]

    by_id = {n.id: n for n in model.nodes}
    neighbours: dict[str, set[str]] = {n.id: set() for n in model.nodes}
    for f in model.flows:
        if f.source_id in by_id and f.target_id in by_id:
            neighbours[f.source_id].add(f.target_id)
            neighbours[f.target_id].add(f.source_id)

    fallback = sorted(valid_ids, key=lambda i: int(i[1:]) if i[1:].isdigit() else 0)[:1]
    changed = True
    while changed:  # propagate outward until stable
        changed = False
        for n in model.nodes:
            if n.source_segment_ids:
                continue
            borrowed = sorted({i for nb in neighbours[n.id] for i in by_id[nb].source_segment_ids})
            if borrowed:
                n.source_segment_ids = borrowed
                n.confidence /= 2
                changed = True
    for n in model.nodes:
        if not n.source_segment_ids:
            n.source_segment_ids = list(fallback)
            n.confidence /= 2
    return model


def extract(llm: LLMProvider, segments: list[Segment]) -> ProcessModel:
    relevant = filter_relevant(llm, segments)
    if not relevant:
        log.warning("filter marked every segment irrelevant; extracting from all of them")
        relevant = segments
    return extract_model(llm, relevant)
