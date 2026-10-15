"""Merge a newly extracted meeting into a project's merged ProcessModel.

1. Entity resolution: lanes and nodes of the new model are matched one-to-one to the merged
   model by embedding similarity of their names. >= merge_auto_match is the same thing,
   < merge_reject is different, and everything in between is confirmed by the LLM ("merge"
   role) in one batch.
2. The merged model is updated ONLY through patch ops (edit.Editor), so user edits are kept
   (nothing is rewritten, names on matched nodes stay as the user left them) and the change
   is a replayable op list stored on the map version.
3. Disagreements are never resolved silently. Each becomes a ConflictDraft (stored as a
   Conflict row + an open question on the map):
   - owner:     a matched step is done by a different role
   - order:     the new meeting puts two known steps in the opposite order (that edge is not added)
   - condition: the same decision path has a different condition (existing one kept)
   - sequence:  a step now has two different "next" steps outside a gateway

Citations in a merged model are qualified as `<transcript_id>:<segment_id>`, so each merged
node carries every transcript and segment it came from.
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.core.config import get_settings
from app.llm.provider import LLMProvider
from app.models.process import GATEWAY_TYPES, TASK_TYPES, Node, OpenQuestion, ProcessModel
from app.pipeline import edit


def qualify(model: ProcessModel, transcript_id: str) -> ProcessModel:
    """Prefix citations with the transcript id (idempotent)."""

    def q(ids: list[str]) -> list[str]:
        return [i if ":" in i else f"{transcript_id}:{i}" for i in ids]

    m = model.model_copy(deep=True)
    for n in m.nodes:
        n.source_segment_ids = q(n.source_segment_ids)
    for oq in m.open_questions:
        oq.source_segment_ids = q(oq.source_segment_ids)
    return m


@dataclass
class ConflictDraft:
    id: str
    kind: str
    description: str
    options: list[str]
    node_ids: list[str]
    sources: list[dict[str, Any]]


@dataclass
class MergeResult:
    model: ProcessModel
    ops: list[dict[str, Any]]
    conflicts: list[ConflictDraft]
    node_map: dict[str, str] = field(default_factory=dict)  # new-model node id -> merged node id


class PairVerdict(BaseModel):
    pair_id: str
    same: bool
    reason: str


class PairVerdicts(BaseModel):
    verdicts: list[PairVerdict]


CONFIRM_PROMPT = """You decide whether two process elements, extracted from two different meetings
about the same business process, are the SAME element (same step, decision, role) described
in different words, or genuinely different ones.

Each input line: `pair_id | existing: <name> | new: <name> | context`.
Answer every pair. `same: true` only if they are the same real-world activity/decision/role.
Different roles doing similar-sounding work are NOT the same. `reason`: at most 12 words."""


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _kind(n: Node) -> str:
    return "task" if n.type in TASK_TYPES else n.type


def resolve(
    llm: LLMProvider,
    base: list[tuple[str, str, str]],
    new: list[tuple[str, str, str]],
    context: Callable[[str, str], str] = lambda a, b: "",
) -> dict[str, str]:
    """Match new items to base items one-to-one. Items are (id, kind, name); only equal kinds
    can match. Returns {new_id: base_id}."""
    s = get_settings()
    if not base or not new:
        return {}
    vectors = llm.embed([name or kind for _, kind, name in base + new])
    vb, vn = vectors[: len(base)], vectors[len(base) :]
    scored = sorted(
        ((_cos(vn[j], vb[i]), n[0], b[0]) for i, b in enumerate(base) for j, n in enumerate(new) if b[1] == n[1]),
        reverse=True,
    )
    matched: dict[str, str] = {}
    used: set[str] = set()
    ambiguous: list[tuple[float, str, str]] = []
    for score, nid, bid in scored:
        if nid in matched or bid in used:
            continue
        if score >= s.merge_auto_match:
            matched[nid] = bid
            used.add(bid)
        elif score >= s.merge_reject:
            ambiguous.append((score, nid, bid))

    pending = [(sc, nid, bid) for sc, nid, bid in ambiguous if nid not in matched and bid not in used]
    if pending:
        names = {i: name for i, _, name in base + new}
        lines = [
            f"p{k} | existing: {names[b]} | new: {names[n]} | {context(b, n)}" for k, (_, n, b) in enumerate(pending)
        ]
        verdicts = llm.structured(CONFIRM_PROMPT, "\n".join(lines), PairVerdicts, "merge").verdicts
        confirmed = {v.pair_id for v in verdicts if v.same}
        for k, (_, nid, bid) in enumerate(pending):  # still best-score-first
            if f"p{k}" in confirmed and nid not in matched and bid not in used:
                matched[nid] = bid
                used.add(bid)
    return matched


def _norm(cond: str | None) -> str:
    return " ".join((cond or "").lower().replace("$", "").replace(",", "").split())


def _reachable(model: ProcessModel, src: str, dst: str, skip: tuple[str, str] | None = None) -> bool:
    out: dict[str, list[str]] = defaultdict(list)
    for f in model.flows:
        if (f.source_id, f.target_id) != skip:
            out[f.source_id].append(f.target_id)
    seen, stack = {src}, [src]
    while stack:
        for nxt in out[stack.pop()]:
            if nxt == dst:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def merge(llm: LLMProvider, base: ProcessModel, new: ProcessModel, transcript_id: str) -> MergeResult:
    """`new` must already be qualified (see qualify())."""
    work = base.model_copy(deep=True)
    editor = edit.Editor(work)
    ops: list[edit.AnyOp] = []

    def do(op: edit.AnyOp) -> None:
        editor.apply([op])
        ops.append(op)

    base_lane_names = {lane.id: lane.name for lane in base.lanes}
    new_lane_names = {lane.id: lane.name for lane in new.lanes}
    base_nodes = {n.id: n for n in base.nodes}
    new_nodes = {n.id: n for n in new.nodes}

    # 1. Entity resolution --------------------------------------------------------------------
    lane_map = resolve(
        llm, [(lane.id, "lane", lane.name) for lane in base.lanes], [(lane.id, "lane", lane.name) for lane in new.lanes]
    )
    node_map: dict[str, str] = {}
    starts_b = [n.id for n in base.nodes if n.type == "start_event"]
    starts_n = [n.id for n in new.nodes if n.type == "start_event"]
    if len(starts_b) == 1 and len(starts_n) == 1:  # one trigger each: same process start
        node_map[starts_n[0]] = starts_b[0]

    def lane_ctx(bid: str, nid: str) -> str:
        return (
            f"existing role: {base_lane_names.get(base_nodes[bid].lane_id, '?')}; new role: "
            f"{new_lane_names.get(new_nodes[nid].lane_id, '?')}"
        )

    # Tasks are compared with their role ("Approve invoice [Finance]" vs "[Accounts Payable]"
    # are different steps); events and gateways by name only.
    def text(n: Node, lanes: dict[str, str]) -> str:
        return f"{n.name} [{lanes.get(n.lane_id, '')}]" if n.type in TASK_TYPES else n.name

    node_map |= resolve(
        llm,
        [(n.id, _kind(n), text(n, base_lane_names)) for n in base.nodes if n.id not in node_map.values()],
        [(n.id, _kind(n), text(n, new_lane_names)) for n in new.nodes if n.id not in node_map],
        lane_ctx,
    )

    conflicts: list[ConflictDraft] = []

    def conflict(kind: str, description: str, options: list[str], node_ids: list[str], sides: list[Node]) -> None:
        sources = [
            {"from": "existing map", "segment_ids": sides[0].source_segment_ids},
            {"from": transcript_id, "segment_ids": sides[-1].source_segment_ids},
        ]
        conflicts.append(ConflictDraft(str(uuid.uuid4()), kind, description, options, node_ids, sources))

    # 2. Lanes the new meeting introduces -----------------------------------------------------
    for lane in new.lanes:
        if lane.id not in lane_map and any(n.lane_id == lane.id and n.id not in node_map for n in new.nodes):
            do(edit.AddLane(op="add_lane", id=lane.id, name=lane.name))
            lane_map[lane.id] = editor.resolve(lane.id)

    # 3. Matched nodes: add citations; flag a different owner ---------------------------------
    for nid, bid in node_map.items():
        new_node, old_node = new_nodes[nid], base_nodes[bid]
        do(edit.AddSources(op="add_sources", node_id=bid, segment_ids=new_node.source_segment_ids))
        if new_node.type in TASK_TYPES and lane_map.get(new_node.lane_id) != old_node.lane_id:
            said = base_lane_names.get(old_node.lane_id, old_node.lane_id)
            claimed = new_lane_names.get(new_node.lane_id, new_node.lane_id)
            conflict(
                "owner",
                f"Who does '{old_node.name}'? The existing map says {said}; the new meeting says {claimed}.",
                [said, claimed],
                [bid],
                [old_node, new_node],
            )

    # 4. New nodes ----------------------------------------------------------------------------
    for n in new.nodes:
        if n.id not in node_map:
            node = n.model_copy(update={"lane_id": lane_map[n.lane_id], "user_added": False})
            do(edit.AddExtractedNode(op="add_extracted_node", node=node))
            node_map[n.id] = editor.resolve(n.id)
    added = {node_map[n.id] for n in new.nodes} - set(base_nodes)

    # 5. Flows --------------------------------------------------------------------------------
    added_edges: set[tuple[str, str]] = set()
    new_edges = {
        (node_map[f.source_id], node_map[f.target_id])
        for f in new.flows
        if f.source_id in node_map and f.target_id in node_map
    }

    def names(node_id: str) -> str:
        return next(x.name for x in work.nodes if x.id == node_id) or node_id

    for f in new.flows:
        if f.source_id not in node_map or f.target_id not in node_map:
            continue
        u, v = node_map[f.source_id], node_map[f.target_id]
        existing = next((x for x in work.flows if x.source_id == u and x.target_id == v), None)
        if existing is not None:
            if f.condition and existing.condition and _norm(f.condition) != _norm(existing.condition):
                conflict(
                    "condition",
                    f"When does '{names(u)}' lead to '{names(v)}'? Existing: \"{existing.condition}\"; "
                    f'new meeting: "{f.condition}".',
                    [existing.condition, f.condition],
                    [u, v],
                    [base_nodes.get(u) or new_nodes[f.source_id], new_nodes[f.source_id]],
                )
            elif f.condition and not existing.condition:
                do(edit.SetCondition(op="set_condition", source_id=u, target_id=v, condition=f.condition))
        elif _reachable(work, u, v):
            continue  # the map already has this path (the new meeting just skipped detail)
        elif u not in added and v not in added and _reachable(work, v, u):
            conflict(
                "order",
                f"Order of '{names(u)}' and '{names(v)}': the existing map has '{names(v)}' first; "
                f"the new meeting has '{names(u)}' first.",
                [f"'{names(v)}' first", f"'{names(u)}' first"],
                [u, v],
                [base_nodes[v], new_nodes[f.source_id]],
            )
        else:
            do(edit.Connect(op="connect", source_id=u, target_id=v, condition=f.condition))
            added_edges.add((u, v))

    # 6. New steps inserted between two existing ones replace the direct link -----------------
    for old in list(base.flows):
        src, dst = old.source_id, old.target_id
        if (src, dst) in new_edges or not any(x.source_id == src and x.target_id in added for x in work.flows):
            continue
        if _reachable_via(work, src, dst, added):
            do(edit.Disconnect(op="disconnect", source_id=src, target_id=dst))

    # 7. A step with two different next steps outside a gateway: ask, don't guess -------------
    for n in work.nodes:
        outs = [x.target_id for x in work.flows if x.source_id == n.id]
        if n.type in GATEWAY_TYPES or len(outs) < 2 or not any((n.id, t) in added_edges for t in outs):
            continue
        conflict(
            "sequence",
            f"What happens after '{n.name}'? The meetings describe different next steps: "
            + ", ".join(f"'{names(t)}'" for t in outs)
            + ". Is it a decision, parallel work, or one of them?",
            [names(t) for t in outs],
            [n.id, *outs],
            [base_nodes.get(n.id) or n, n],
        )

    # 8. Surface every conflict as an open question on the map --------------------------------
    for c in conflicts:
        cites = sorted({s for side in c.sources for s in side["segment_ids"]})
        q = OpenQuestion(
            id=f"conflict_{c.id}",
            question=f"Meetings disagree ({c.kind}): {c.description} Options: " + " | ".join(c.options),
            related_node_ids=c.node_ids,
            source_segment_ids=cites,
        )
        do(edit.AddOpenQuestion(op="add_open_question", question=q))

    return MergeResult(model=work, ops=[o.model_dump() for o in ops], conflicts=conflicts, node_map=node_map)


def _reachable_via(model: ProcessModel, a: str, b: str, through: set[str]) -> bool:
    """Is there a path a -> ... -> b whose intermediate nodes are all in `through`?"""
    out: dict[str, list[str]] = defaultdict(list)
    for f in model.flows:
        out[f.source_id].append(f.target_id)
    stack = [t for t in out[a] if t in through]
    seen = set(stack)
    while stack:
        for nxt in out[stack.pop()]:
            if nxt == b:
                return True
            if nxt in through and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


class CannotApply(ValueError):
    """The chosen option needs a judgement call; the user edits the map, then marks it resolved."""


def resolution_ops(
    kind: str, node_ids: list[str], options: list[str], choice: int, model: ProcessModel
) -> list[edit.AnyOp]:
    """Patch ops that make the map say what the chosen conflict option says.

    Option 0 is always "keep what the map says" for owner/order/condition conflicts.
    """
    if not 0 <= choice < len(options):
        raise CannotApply(f"option must be 0..{len(options) - 1}")
    nodes = {n.id: n for n in model.nodes}
    if any(nid not in nodes for nid in node_ids):
        raise CannotApply("the steps this conflict refers to were changed or removed; edit the map directly")

    if kind == "owner":
        (nid,) = node_ids
        name = options[choice]
        lane = next((lane.id for lane in model.lanes if lane.name.strip().lower() == name.strip().lower()), None)
        ops: list[edit.AnyOp] = []
        if lane is None:
            lane = "lane_" + "_".join(name.lower().split())[:40]
            ops.append(edit.AddLane(op="add_lane", id=lane, name=name))
        ops.append(edit.ReassignLane(op="reassign_lane", node_id=nid, lane_id=lane))
        return ops

    if kind == "condition":
        u, v = node_ids
        return [edit.SetCondition(op="set_condition", source_id=u, target_id=v, condition=options[choice])]

    if kind == "sequence":
        n, *targets = node_ids
        keep = targets[choice]
        return [edit.Disconnect(op="disconnect", source_id=n, target_id=t) for t in targets if t != keep]

    if kind == "order":
        if choice == 0:
            return []
        first, second = node_ids  # the new meeting says `first` comes before `second`
        out = {(f.source_id, f.target_id): f.condition for f in model.flows}
        if (second, first) not in out or any(nodes[i].type not in TASK_TYPES for i in node_ids):
            raise CannotApply("these steps aren't directly next to each other; reorder them in the editor")
        preds = [(s, c) for (s, t), c in out.items() if t == second]
        succs = [(t, c) for (s, t), c in out.items() if s == first]
        ops = []
        for s, c in preds:  # ... -> second -> first -> ...  becomes  ... -> first -> second -> ...
            ops += [
                edit.Disconnect(op="disconnect", source_id=s, target_id=second),
                edit.Connect(op="connect", source_id=s, target_id=first, condition=c),
            ]
        ops += [edit.Disconnect(op="disconnect", source_id=second, target_id=first)]
        for t, c in succs:
            ops += [
                edit.Disconnect(op="disconnect", source_id=first, target_id=t),
                edit.Connect(op="connect", source_id=second, target_id=t, condition=c),
            ]
        ops.append(edit.Connect(op="connect", source_id=first, target_id=second, condition=None))
        return ops

    raise CannotApply(f"unknown conflict kind {kind!r}")
