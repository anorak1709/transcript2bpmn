"""Chat editing: the LLM returns typed patch ops; deterministic code applies them.

The LLM never rewrites the whole model, so an edit can't silently drop or rename things
the user didn't mention, and every change is a reviewable, replayable list of ops.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.llm.provider import LLMProvider
from app.models.process import TASK_TYPES, Flow, Lane, Node, ProcessModel
from app.pipeline.extract import load_prompt

EDIT_PROMPT = "edit_v1"


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddTask(_Op):
    op: Literal["add_task"]
    id: str
    name: str
    type: Literal["user_task", "service_task"]
    lane_id: str
    insert_after: str | None  # node id: new task takes over its outgoing flows


class RemoveNode(_Op):
    op: Literal["remove_node"]
    node_id: str
    reconnect: bool  # connect predecessors straight to successors


class RenameNode(_Op):
    op: Literal["rename_node"]
    node_id: str
    name: str


class MergeTasks(_Op):
    op: Literal["merge_tasks"]
    node_ids: list[str]  # first one survives
    name: str


class SplitTask(_Op):
    op: Literal["split_task"]
    node_id: str
    names: list[str]  # >= 2, in execution order


class ReassignLane(_Op):
    op: Literal["reassign_lane"]
    node_id: str
    lane_id: str


class AddLane(_Op):
    op: Literal["add_lane"]
    id: str
    name: str


class AddGateway(_Op):
    op: Literal["add_gateway"]
    id: str
    type: Literal["exclusive_gateway", "parallel_gateway"]
    name: str
    lane_id: str
    insert_after: str | None


class Connect(_Op):
    op: Literal["connect"]
    source_id: str
    target_id: str
    condition: str | None


class Disconnect(_Op):
    op: Literal["disconnect"]
    source_id: str
    target_id: str


class SetCondition(_Op):
    op: Literal["set_condition"]
    source_id: str
    target_id: str
    condition: str | None


class ResolveOpenQuestion(_Op):
    op: Literal["resolve_open_question"]
    question_id: str


# Plain union, not a pydantic discriminator: OpenAI strict mode accepts anyOf but not oneOf.
# The `op` literal still makes each variant unambiguous.
PatchOp = (
    AddTask
    | RemoveNode
    | RenameNode
    | MergeTasks
    | SplitTask
    | ReassignLane
    | AddLane
    | AddGateway
    | Connect
    | Disconnect
    | SetCondition
    | ResolveOpenQuestion
)


class EditPlan(_Op):
    ops: list[PatchOp]
    reply: str  # one or two sentences back to the user


class OpError(ValueError):
    pass


def apply_ops(model: ProcessModel, ops: list[PatchOp]) -> ProcessModel:
    """Apply ops in order to a copy of `model`. All-or-nothing: raises OpError on the first
    op that references something that doesn't exist (the original model is untouched)."""
    return _Editor(model.model_copy(deep=True)).apply(ops)


class _Editor:
    def __init__(self, m: ProcessModel) -> None:
        self.m = m
        self.renamed: dict[str, str] = {}  # requested new id -> id actually used

    def apply(self, ops: list[PatchOp]) -> ProcessModel:
        for i, op in enumerate(ops, 1):
            try:
                getattr(self, op.op)(op)
            except OpError as e:
                raise OpError(f"op {i} ({op.op}): {e}") from None
        return self.m

    # helpers -------------------------------------------------------------------------------
    def node(self, nid: str) -> Node:
        nid = self.renamed.get(nid, nid)
        for n in self.m.nodes:
            if n.id == nid:
                return n
        raise OpError(f"no node {nid!r}")

    def lane(self, lid: str) -> str:
        lid = self.renamed.get(lid, lid)
        if not any(lane.id == lid for lane in self.m.lanes):
            raise OpError(f"no lane {lid!r}")
        return lid

    def fresh(self, wanted: str, taken: set[str]) -> str:
        new, k = wanted, 2
        while new in taken:
            new, k = f"{wanted}_{k}", k + 1
        self.renamed[wanted] = new
        return new

    def flow_id(self) -> str:
        taken = {f.id for f in self.m.flows}
        k = len(taken) + 1
        while f"f{k}" in taken:
            k += 1
        return f"f{k}"

    def link(self, src: str, tgt: str, condition: str | None = None) -> None:
        if src != tgt and not any(f.source_id == src and f.target_id == tgt for f in self.m.flows):
            self.m.flows.append(Flow(id=self.flow_id(), source_id=src, target_id=tgt, condition=condition))

    def flow(self, src: str, tgt: str) -> Flow:
        s, t = self.node(src).id, self.node(tgt).id
        for f in self.m.flows:
            if f.source_id == s and f.target_id == t:
                return f
        raise OpError(f"no flow {s!r} -> {t!r}")

    def add_node(self, wanted_id: str, type_: str, name: str, lane_id: str, insert_after: str | None) -> None:
        lane = self.lane(lane_id)
        after = self.node(insert_after).id if insert_after else None
        nid = self.fresh(wanted_id, {n.id for n in self.m.nodes})
        self.m.nodes.append(
            Node.model_validate(
                {
                    "id": nid,
                    "type": type_,
                    "name": name,
                    "lane_id": lane,
                    "source_segment_ids": [],
                    "confidence": 1.0,
                    "user_added": True,
                }
            )
        )
        if after:
            for f in self.m.flows:  # new node takes over `after`'s outgoing flows
                if f.source_id == after:
                    f.source_id = nid
            self.link(after, nid)

    # ops ------------------------------------------------------------------------------------
    def add_task(self, op: AddTask) -> None:
        self.add_node(op.id, op.type, op.name, op.lane_id, op.insert_after)

    def add_gateway(self, op: AddGateway) -> None:
        self.add_node(op.id, op.type, op.name, op.lane_id, op.insert_after)

    def add_lane(self, op: AddLane) -> None:
        lid = self.fresh(op.id, {lane.id for lane in self.m.lanes})
        self.m.lanes.append(Lane(id=lid, name=op.name))

    def remove_node(self, op: RemoveNode) -> None:
        nid = self.node(op.node_id).id
        incoming = [f for f in self.m.flows if f.target_id == nid]
        outgoing = [f for f in self.m.flows if f.source_id == nid]
        self.m.nodes = [n for n in self.m.nodes if n.id != nid]
        self.m.flows = [f for f in self.m.flows if nid not in (f.source_id, f.target_id)]
        if op.reconnect:
            for i in incoming:
                for o in outgoing:
                    self.link(i.source_id, o.target_id, i.condition)
        for q in self.m.open_questions:
            q.related_node_ids = [r for r in q.related_node_ids if r != nid]

    def rename_node(self, op: RenameNode) -> None:
        self.node(op.node_id).name = op.name

    def reassign_lane(self, op: ReassignLane) -> None:
        self.node(op.node_id).lane_id = self.lane(op.lane_id)

    def merge_tasks(self, op: MergeTasks) -> None:
        nodes = [self.node(i) for i in op.node_ids]
        if len(nodes) < 2 or any(n.type not in TASK_TYPES for n in nodes):
            raise OpError("merge_tasks needs 2+ task nodes")
        keep, others = nodes[0], {n.id for n in nodes[1:]}
        keep.name = op.name
        keep.source_segment_ids = sorted({s for n in nodes for s in n.source_segment_ids})
        keep.confidence = max(n.confidence for n in nodes)
        keep.user_added = all(n.user_added for n in nodes)
        flows, self.m.flows = self.m.flows, []
        self.m.nodes = [n for n in self.m.nodes if n.id not in others]
        for f in flows:
            src = keep.id if f.source_id in others else f.source_id
            tgt = keep.id if f.target_id in others else f.target_id
            self.link(src, tgt, f.condition)  # drops self-loops and duplicates the merge creates
        for q in self.m.open_questions:
            q.related_node_ids = list(dict.fromkeys(keep.id if r in others else r for r in q.related_node_ids))

    def split_task(self, op: SplitTask) -> None:
        first = self.node(op.node_id)
        if first.type not in TASK_TYPES or len(op.names) < 2:
            raise OpError("split_task needs a task and 2+ names")
        first.name = op.names[0]
        prev = first.id
        for k, name in enumerate(op.names[1:], 2):
            nid = self.fresh(f"{first.id}_{k}", {n.id for n in self.m.nodes})
            # Same transcript evidence as the original: a split refines, it doesn't invent.
            self.m.nodes.append(first.model_copy(update={"id": nid, "name": name}))
            for f in self.m.flows:
                if f.source_id == prev:
                    f.source_id = nid
            self.link(prev, nid)
            prev = nid

    def connect(self, op: Connect) -> None:
        s, t = self.node(op.source_id).id, self.node(op.target_id).id
        if any(f.source_id == s and f.target_id == t for f in self.m.flows):
            raise OpError(f"{s!r} -> {t!r} already connected")
        self.link(s, t, op.condition)

    def disconnect(self, op: Disconnect) -> None:
        f = self.flow(op.source_id, op.target_id)
        self.m.flows = [x for x in self.m.flows if x is not f]

    def set_condition(self, op: SetCondition) -> None:
        self.flow(op.source_id, op.target_id).condition = op.condition or None

    def resolve_open_question(self, op: ResolveOpenQuestion) -> None:
        before = len(self.m.open_questions)
        self.m.open_questions = [q for q in self.m.open_questions if q.id != op.question_id]
        if len(self.m.open_questions) == before:
            raise OpError(f"no open question {op.question_id!r}")


def plan_edit(llm: LLMProvider, model: ProcessModel, instruction: str) -> tuple[ProcessModel, EditPlan]:
    """Ask the LLM ("edit" role) for ops and apply them. One retry, with the error shown to
    the LLM, if the ops don't apply; raises OpError if the retry fails too."""
    prompt = load_prompt(EDIT_PROMPT)
    payload = f"## Current model\n{model.model_dump_json()}\n\n## User instruction\n{instruction}"
    plan = llm.structured(prompt, payload, EditPlan, "edit")
    try:
        return apply_ops(model, plan.ops), plan
    except OpError as e:
        retry = f"{payload}\n\n## Your previous ops failed\n{e}\nReturn corrected ops."
        plan = llm.structured(prompt, retry, EditPlan, "edit", metadata={"retry_after": str(e)})
        return apply_ops(model, plan.ops), plan
