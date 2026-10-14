"""Two-pass extraction: relevance filter, then structured ProcessModel extraction."""

import logging
from pathlib import Path

from pydantic import BaseModel

from app.llm.provider import LLMProvider
from app.models.process import Node, OpenQuestion, ProcessModel
from app.models.transcript import Segment
from app.pipeline.normalize import render

log = logging.getLogger(__name__)

PROMPTS = Path(__file__).parent / "prompts"
FILTER_PROMPT = "filter_v1"
EXTRACT_PROMPT = "extract_v1"
BATCH_CHARS = 12_000  # ~3k tokens of transcript per filter call


def load_prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


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


def extract_model(llm: LLMProvider, segments: list[Segment]) -> ProcessModel:
    # ponytail: one extraction call over all relevant segments. Long meetings that overflow
    # the context window need chunked extraction + merge (the Phase 4 merge step covers that).
    model = llm.structured(load_prompt(EXTRACT_PROMPT), render(segments), ProcessModel, "extract")
    return enforce_citations(model, {s.segment_id for s in segments})


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
