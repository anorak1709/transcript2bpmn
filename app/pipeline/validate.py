"""Deterministic graph checks on a ProcessModel, plus the LLM repair loop."""

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass

from pydantic import BaseModel

from app.llm.provider import LLMProvider
from app.models.process import GATEWAY_TYPES, OpenQuestion, ProcessModel
from app.models.transcript import Segment
from app.pipeline.extract import enforce_citations
from app.pipeline.normalize import render
from app.pipeline.prompts import load_prompt

log = logging.getLogger(__name__)

REPAIR_PROMPT = "repair_v1"
MAX_REPAIR_ATTEMPTS = 2


class ValidationError(BaseModel):
    code: str
    message: str
    node_ids: list[str]


def validate(model: ProcessModel) -> list[ValidationError]:
    errors: list[ValidationError] = []

    def err(code: str, message: str, node_ids: list[str] | None = None) -> None:
        errors.append(ValidationError(code=code, message=message, node_ids=node_ids or []))

    for kind, ids in (
        ("lane", [lane.id for lane in model.lanes]),
        ("node", [n.id for n in model.nodes]),
        ("flow", [f.id for f in model.flows]),
    ):
        for dup, count in Counter(ids).items():
            if count > 1:
                err("DUPLICATE_ID", f"{count} {kind}s share the id {dup!r}", [dup] if kind == "node" else [])

    nodes = {n.id: n for n in model.nodes}
    lane_ids = {lane.id for lane in model.lanes}
    for n in model.nodes:
        if n.lane_id not in lane_ids:
            err("INVALID_LANE", f"{n.name or n.id!r} is in lane {n.lane_id!r}, which doesn't exist", [n.id])

    out: dict[str, list[str]] = defaultdict(list)
    inc: dict[str, list[str]] = defaultdict(list)
    for f in model.flows:
        missing = [i for i in (f.source_id, f.target_id) if i not in nodes]
        if missing:
            err("DANGLING_FLOW", f"Flow {f.id!r} references missing node(s) {missing}", [i for i in missing])
            continue
        out[f.source_id].append(f.target_id)
        inc[f.target_id].append(f.source_id)

    starts = [n for n in model.nodes if n.type == "start_event"]
    ends = [n for n in model.nodes if n.type == "end_event"]
    start_lanes = Counter(n.lane_id for n in starts)
    if not starts:
        err("NO_START_EVENT", "The process has no start event")
    elif len(starts) > 1 and max(start_lanes.values()) > 1:
        # One start per lane is allowed (explicitly modeled per-role triggers); several in one lane isn't.
        err("MULTIPLE_START_EVENTS", f"{len(starts)} start events; expected one", [n.id for n in starts])
    if not ends:
        err("NO_END_EVENT", "The process has no end event")

    orphans = {n.id for n in model.nodes if not out[n.id] and not inc[n.id]}
    for nid in orphans:
        if len(nodes) > 1:
            err("ORPHAN_NODE", f"{nodes[nid].name or nid!r} isn't connected to anything", [nid])

    reachable = _walk([n.id for n in starts], out)
    can_end = _walk([n.id for n in ends], inc)
    for n in model.nodes:
        if n.id in orphans:
            continue
        if starts and n.id not in reachable:
            err("UNREACHABLE", f"{n.name or n.id!r} can't be reached from the start", [n.id])
        if ends and n.id not in can_end:
            err("DEAD_END", f"{n.name or n.id!r} never leads to an end event", [n.id])

    conditions = {(f.source_id, f.target_id): f.condition for f in model.flows}
    for n in model.nodes:
        if n.type not in GATEWAY_TYPES or n.id in orphans:
            continue
        if len(inc[n.id]) <= 1 and len(out[n.id]) < 2:
            err("GATEWAY_NO_BRANCH", f"Gateway {n.name or n.id!r} splits into fewer than 2 paths", [n.id])
        if n.type == "exclusive_gateway" and len(out[n.id]) >= 2:
            unlabeled = [t for t in out[n.id] if not (conditions.get((n.id, t)) or "").strip()]
            if unlabeled:
                err(
                    "MISSING_CONDITION",
                    f"Decision {n.name or n.id!r} has {len(unlabeled)} outgoing path(s) without a condition",
                    [n.id, *unlabeled],
                )
    return errors


def _walk(roots: list[str], edges: dict[str, list[str]]) -> set[str]:
    seen, stack = set(roots), list(roots)
    while stack:
        for nxt in edges[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


@dataclass
class RepairResult:
    model: ProcessModel
    repair_attempts: int
    unresolved_errors: list[ValidationError]


def repair(llm: LLMProvider, model: ProcessModel, segments: list[Segment]) -> RepairResult:
    """Validate; if broken, ask the LLM ("repair" role) for a corrected model, up to
    MAX_REPAIR_ATTEMPTS times. Keeps the version with the fewest errors and turns whatever
    is still wrong into OpenQuestions. Never raises on an invalid model."""
    best, best_errors = model, validate(model)
    attempts = 0
    valid_ids = {s.segment_id for s in segments}
    while best_errors and attempts < MAX_REPAIR_ATTEMPTS:
        attempts += 1
        payload = _repair_input(best, best_errors, segments)
        try:
            candidate = llm.structured(
                load_prompt(REPAIR_PROMPT),
                payload,
                ProcessModel,
                "repair",
                metadata={"repair_attempt": attempts, "error_codes": sorted({e.code for e in best_errors})},
            )
        except Exception:
            log.exception("repair attempt %d failed", attempts)
            continue
        candidate = enforce_citations(candidate, valid_ids)
        candidate_errors = validate(candidate)
        log.info("repair attempt %d: %d -> %d errors", attempts, len(best_errors), len(candidate_errors))
        if len(candidate_errors) < len(best_errors):
            best, best_errors = candidate, candidate_errors

    if best_errors:
        best = errors_to_questions(best, best_errors)
    log.info("validation: %d repair attempts, %d unresolved errors", attempts, len(best_errors))
    return RepairResult(model=best, repair_attempts=attempts, unresolved_errors=best_errors)


def errors_to_questions(model: ProcessModel, errors: list[ValidationError]) -> ProcessModel:
    node_ids = {n.id for n in model.nodes}
    cited = {n.id: n.source_segment_ids for n in model.nodes}
    questions = list(model.open_questions)
    for i, e in enumerate(errors, 1):
        related = [nid for nid in dict.fromkeys(e.node_ids) if nid in node_ids]
        questions.append(
            OpenQuestion(
                id=f"validation_{i}",
                question=f"Needs review ({e.code}): {e.message}",
                related_node_ids=related,
                source_segment_ids=sorted({s for nid in related for s in cited[nid]}),
            )
        )
    return model.model_copy(update={"open_questions": questions})


def _repair_input(model: ProcessModel, errors: list[ValidationError], segments: list[Segment]) -> str:
    """Model + errors + the transcript lines the broken nodes (and their neighbours) cite."""
    involved = {nid for e in errors for nid in e.node_ids}
    for f in model.flows:
        if f.source_id in involved or f.target_id in involved:
            involved |= {f.source_id, f.target_id}
    cited = {s for n in model.nodes if n.id in involved for s in n.source_segment_ids}
    # Global problems (no start/end event) name no nodes: give the whole transcript.
    relevant = [s for s in segments if s.segment_id in cited] if cited else segments
    return "\n\n".join(
        [
            "## Current model\n" + model.model_dump_json(),
            "## Validation errors\n" + json.dumps([e.model_dump() for e in errors], indent=1),
            "## Source transcript segments\n" + render(relevant),
        ]
    )
