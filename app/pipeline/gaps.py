"""What nobody said: places in a map where the meetings left something out.

Deterministic and free (no LLM). Each gap carries a ready-to-ask question for the next
meeting (app/agenda.py). Gap ids are stable across map versions (kind + node id), so a gap
the user dismissed stays dismissed.
"""

import hashlib
import re
from dataclasses import dataclass

from app.models.process import TASK_TYPES, ProcessModel

# Lanes the extraction uses when nobody said who does a step.
_NO_OWNER = re.compile(r"^(unassigned|unknown|unspecified|tbd|n/?a|other)\b", re.I)
# Steps that can go wrong: they need a "what if not?" path.
# ponytail: verb list, English only; widen it when real maps show misses.
_CHECKS = re.compile(r"\b(approve|approval|review|check|verify|validate|confirm|sign[- ]off|match|inspect|audit)", re.I)


@dataclass
class Gap:
    id: str
    kind: str  # one_outcome | no_owner | dead_end | no_trigger | no_exception
    node_ids: list[str]
    description: str  # what's missing, for the gaps list
    question: str  # what to ask, for the agenda


def _gap(kind: str, node_id: str, description: str, question: str) -> Gap:
    gid = hashlib.sha1(f"{kind}:{node_id}".encode()).hexdigest()[:12]
    return Gap(gid, kind, [node_id], description, question)


def find_gaps(model: ProcessModel) -> list[Gap]:
    lanes = {lane.id: lane.name for lane in model.lanes}
    out_of: dict[str, list[str]] = {n.id: [] for n in model.nodes}
    into: dict[str, list[str]] = {n.id: [] for n in model.nodes}
    cond: dict[tuple[str, str], str | None] = {}
    for f in model.flows:
        out_of.setdefault(f.source_id, []).append(f.target_id)
        into.setdefault(f.target_id, []).append(f.source_id)
        cond[(f.source_id, f.target_id)] = f.condition
    names = {n.id: n.name or "an unnamed step" for n in model.nodes}
    types = {n.id: n.type for n in model.nodes}
    gaps: list[Gap] = []

    for n in model.nodes:
        outs, ins = out_of[n.id], into[n.id]
        name = names[n.id]

        if n.type == "exclusive_gateway" and len(outs) == 1 and len(ins) <= 1:  # a split, not a join
            only = cond.get((n.id, outs[0])) or names[outs[0]]
            gaps.append(
                _gap(
                    "one_outcome",
                    n.id,
                    f"Only one outcome of '{name}' was described ({only}).",
                    f"For '{name}': we heard what happens when it's '{only}'. What happens otherwise?",
                )
            )

        if n.type in TASK_TYPES and (n.lane_id not in lanes or _NO_OWNER.match(lanes[n.lane_id].strip())):
            gaps.append(
                _gap("no_owner", n.id, f"Nobody said who does '{name}'.", f"Who does '{name}'? Which team or role?")
            )

        if n.type != "end_event" and not outs:
            gaps.append(
                _gap(
                    "dead_end",
                    n.id,
                    f"Nothing follows '{name}': it's handed off to nobody.",
                    f"After '{name}', what happens next, and who picks it up?",
                )
            )

        if n.type != "start_event" and not ins:
            gaps.append(
                _gap(
                    "no_trigger",
                    n.id,
                    f"Nothing leads to '{name}'.",
                    f"What starts '{name}'? What happens just before it?",
                )
            )

        if (
            n.type in TASK_TYPES
            and _CHECKS.search(n.name)
            and not any(
                types.get(t) == "exclusive_gateway" and len(out_of[t]) > 1
                for t in outs  # a split, not a join
            )
        ):
            gaps.append(
                _gap(
                    "no_exception",
                    n.id,
                    f"No path for when '{name}' fails or is rejected.",
                    f"What happens when '{name}' doesn't pass, e.g. it's rejected or something is wrong?",
                )
            )
    return gaps
