"""Improvement suggestions: where the process could be faster or cheaper, from the map alone.

Rules are free and explainable (each says which pattern it saw). `ai_ideas` asks the LLM for
more, and costs credits only when a person asks for it.
"""

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.llm.provider import LLMProvider
from app.models.process import TASK_TYPES, ProcessModel
from app.pipeline.prompts import load_prompt

# ponytail: English verb lists; widen when real maps show misses.
# Work that moves, copies or checks data: the classic automation candidates.
_DATA_WORK = re.compile(
    r"\b(enter|key|re-?type|copy|paste|upload|download|export|import|send|e-?mail|forward|file|record|log|"
    r"update|look up|lookup|match|compare|reconcile|check .{0,30}against|calculate|fill in|scan|print|notify)",
    re.I,
)
_APPROVAL = re.compile(r"\b(approv\w*|sign[- ]?off|authori[sz]\w*|review|countersign)", re.I)


@dataclass
class Suggestion:
    kind: str  # automate | handoff | approvals | ai
    title: str
    detail: str
    node_ids: list[str]
    id: str = field(default="")

    def __post_init__(self) -> None:
        self.id = self.id or hashlib.sha1(f"{self.kind}:{','.join(self.node_ids)}".encode()).hexdigest()[:12]


def suggest(model: ProcessModel) -> list[Suggestion]:
    nodes = {n.id: n for n in model.nodes}
    lanes = {x.id: x.name for x in model.lanes}
    out_of: dict[str, list[str]] = defaultdict(list)
    for f in model.flows:
        out_of[f.source_id].append(f.target_id)
    tasks = [n for n in model.nodes if n.type in TASK_TYPES]
    found: list[Suggestion] = []

    # 1. Automation candidates: a person doing data work.
    for n in tasks:
        if n.type == "user_task" and _DATA_WORK.search(n.name):
            found.append(
                Suggestion(
                    "automate",
                    f"Automate '{n.name}'",
                    f"{lanes.get(n.lane_id, 'Someone')} does this by hand, and it moves or checks data: "
                    "a candidate for an integration, a rule in the system, or an RPA bot.",
                    [n.id],
                )
            )

    # 2. Handoffs: work crossing between teams, and work bouncing back to where it came from.
    def next_tasks(nid: str, seen: frozenset[str] = frozenset()) -> list[str]:
        """The next steps after nid, looking through gateways."""
        result = []
        for t in out_of.get(nid, []):
            if t in seen or t not in nodes:
                continue
            if nodes[t].type in TASK_TYPES:
                result.append(t)
            else:
                result += next_tasks(t, seen | {nid})
        return result

    crossings: Counter[str] = Counter()
    for n in tasks:
        for t in next_tasks(n.id):
            if nodes[t].lane_id != n.lane_id:
                crossings[nodes[t].lane_id] += 1
                for back in next_tasks(t):
                    if nodes[back].lane_id == n.lane_id and back != n.id:
                        found.append(
                            Suggestion(
                                "handoff",
                                f"Work bounces between {lanes.get(n.lane_id, '?')} and "
                                f"{lanes.get(nodes[t].lane_id, '?')}",
                                f"'{n.name}' hands over to '{nodes[t].name}', which hands straight back to "
                                f"'{nodes[back].name}'. Could one team do both, or the hand-back be removed?",
                                [n.id, t, back],
                            )
                        )
    if crossings:
        lane_id, count = crossings.most_common(1)[0]
        if count >= 2:
            found.append(
                Suggestion(
                    "handoff",
                    f"Handoffs pile up at {lanes.get(lane_id, '?')}",
                    f"{count} different steps hand work over to {lanes.get(lane_id, '?')}. Queues form at busy "
                    "handoffs: worth checking its capacity and turnaround.",
                    [n.id for n in tasks if n.lane_id == lane_id],
                )
            )

    # 3. Approvals that may duplicate each other: one approval directly after another.
    approvals = [n for n in tasks if _APPROVAL.search(n.name)]
    for a in approvals:
        for b in next_tasks(a.id):
            if _APPROVAL.search(nodes[b].name):
                found.append(
                    Suggestion(
                        "approvals",
                        "Two approvals in a row",
                        f"'{a.name}' ({lanes.get(a.lane_id, '?')}) is followed straight away by '{nodes[b].name}' "
                        f"({lanes.get(nodes[b].lane_id, '?')}). Does the second add a different check, or could a "
                        "threshold decide which one is needed?",
                        [a.id, b],
                    )
                )
    if len(approvals) >= 3:
        found.append(
            Suggestion(
                "approvals",
                f"{len(approvals)} approval steps",
                "Many approvals usually mean long waits. Check whether each one guards a distinct risk.",
                [a.id for a in approvals],
            )
        )
    unique: dict[str, Suggestion] = {}
    for s in found:
        unique.setdefault(s.id, s)
    return list(unique.values())


class _Idea(BaseModel):
    title: str
    detail: str
    step_names: list[str]


class _Ideas(BaseModel):
    ideas: list[_Idea]


def ai_ideas(llm: LLMProvider, model: ProcessModel, already: list[Suggestion]) -> list[Suggestion]:
    """More ideas from the LLM ("edit" role), beyond what the rules found. Costs credits."""
    names = {n.name.lower(): n.id for n in model.nodes}
    payload = f"## Process\n{model.model_dump_json()}\n\n## Already suggested\n" + "\n".join(
        f"- {s.title}" for s in already
    )
    result = llm.structured(load_prompt("improve_v1"), payload, _Ideas, "edit")
    return [
        Suggestion("ai", i.title, i.detail, [names[x.lower()] for x in i.step_names if x.lower() in names])
        for i in result.ideas
    ]
