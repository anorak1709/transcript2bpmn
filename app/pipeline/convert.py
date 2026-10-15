"""ProcessModel -> BPMN 2.0 XML (semantic model + diagram layout). Deterministic, no LLM.

Layout: bpmn-auto-layout (bpmn-io) was evaluated and rejected; it only lays out the first
participant and has no lane placement (lanes get a default size, nodes ignore them).
So: x = column from longest-path layering over the flow DAG (back edges ignored),
y = lane band, with sub-rows when several nodes of one lane share a column.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from lxml import etree

from app.models.process import Flow, Node, ProcessModel

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DI = "http://www.omg.org/spec/DD/20100524/DI"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
NSMAP = {"bpmn": BPMN, "bpmndi": BPMNDI, "dc": DC, "di": DI, "xsi": XSI}
XSD = Path(__file__).parent / "xsd" / "BPMN20.xsd"

TAG = {
    "start_event": "startEvent",
    "end_event": "endEvent",
    "user_task": "userTask",
    "service_task": "serviceTask",
    "exclusive_gateway": "exclusiveGateway",
    "parallel_gateway": "parallelGateway",
}
SIZE = {"start_event": (36, 36), "end_event": (36, 36), "exclusive_gateway": (50, 50), "parallel_gateway": (50, 50)}
TASK_SIZE = (100, 80)

ORIGIN_X, ORIGIN_Y = 160, 80
POOL_LABEL_W = 30  # participant's vertical name band
PAD_X = 40
COL_W, ROW_H = 160, 120
UNASSIGNED_LANE = "unassigned"


def xml_id(prefix: str, model_id: str) -> str:
    """XML ids must be NCNames (no leading digit, no spaces). Prefix makes them so and keeps
    the model id recoverable: Node_t1 <-> t1."""
    return f"{prefix}_{re.sub(r'[^A-Za-z0-9_.-]', '_', model_id)}"


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class Layout:
    pool: Box
    lanes: dict[str, Box]
    nodes: dict[str, Box]
    edges: dict[str, list[tuple[float, float]]]


def _clean(model: ProcessModel) -> tuple[list[tuple[str, str]], list[Node], list[Flow]]:
    """Make any model drawable as valid XML: duplicate ids dropped (first wins), unknown
    lanes -> 'Unassigned', dangling flows dropped.

    validate.py reports these problems; this only guarantees the XML stays well-formed even
    when the repair loop couldn't fix them.
    """
    lanes = list({lane.id: (lane.id, lane.name) for lane in reversed(model.lanes)}.values())[::-1]
    lane_ids = {lid for lid, _ in lanes}
    unique_nodes = list({n.id: n for n in reversed(model.nodes)}.values())[::-1]
    nodes = [n if n.lane_id in lane_ids else n.model_copy(update={"lane_id": UNASSIGNED_LANE}) for n in unique_nodes]
    if any(n.lane_id == UNASSIGNED_LANE for n in nodes) and UNASSIGNED_LANE not in lane_ids:
        lanes.append((UNASSIGNED_LANE, "Unassigned"))
    node_ids = {n.id for n in nodes}
    unique_flows = list({f.id: f for f in reversed(model.flows)}.values())[::-1]
    flows = [f for f in unique_flows if f.source_id in node_ids and f.target_id in node_ids]
    return lanes, nodes, flows


def _columns(nodes: list[Node], flows: list[Flow]) -> tuple[dict[str, int], set[str]]:
    """Longest-path layering. Returns (column per node, ids of back-edge flows)."""
    out: dict[str, list[Flow]] = defaultdict(list)
    for f in flows:
        out[f.source_id].append(f)

    back: set[str] = set()
    state: dict[str, int] = {}  # 1 = on DFS stack, 2 = done
    starts = [n.id for n in nodes if n.type == "start_event"] + [n.id for n in nodes]
    for root in starts:
        if root in state:
            continue
        stack = [(root, iter(out[root]))]
        state[root] = 1
        while stack:
            nid, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[nid] = 2
                stack.pop()
            elif state.get(nxt.target_id) == 1:
                back.add(nxt.id)
            elif nxt.target_id not in state:
                state[nxt.target_id] = 1
                stack.append((nxt.target_id, iter(out[nxt.target_id])))

    col = {n.id: 0 for n in nodes}
    forward = [f for f in flows if f.id not in back]
    indeg = {n.id: 0 for n in nodes}
    for f in forward:
        indeg[f.target_id] += 1
    ready = [n.id for n in nodes if indeg[n.id] == 0]
    while ready:
        nid = ready.pop()
        for f in out[nid]:
            if f.id in back:
                continue
            col[f.target_id] = max(col[f.target_id], col[nid] + 1)
            indeg[f.target_id] -= 1
            if indeg[f.target_id] == 0:
                ready.append(f.target_id)
    return col, back


@dataclass
class KeptPositions:
    """What the current diagram looks like, so regeneration can keep it.

    nodes: node id -> (lane id, x, y offset from the lane's top, absolute y). Lane-relative y
           survives lanes being added, removed or resized above it.
    edges: flow id -> waypoints, reused when both ends are exactly where they were.
    """

    nodes: dict[str, tuple[str, float, float, float]] = field(default_factory=dict)
    edges: dict[str, list[tuple[float, float]]] = field(default_factory=dict)


GAP_X = COL_W - TASK_SIZE[0]  # horizontal space between consecutive steps


def layout(model: ProcessModel, keep: KeptPositions | None = None) -> Layout:
    """Lay out the model. Nodes in `keep` that are still in the same lane stay where they
    were (e.g. where the user dragged them); everything else gets the computed position.

    A node inserted between kept ones goes just right of its predecessors, and the kept
    nodes downstream of it shift right together (their arrangement intact) to make room.
    """
    lanes, nodes, flows = _clean(model)
    col, back = _columns(nodes, flows)
    keep = keep or KeptPositions()
    lane_of = {n.id: n.lane_id for n in nodes}
    kept = {nid: k for nid, k in keep.nodes.items() if lane_of.get(nid) == k[0]}

    cells: dict[tuple[str, int], list[Node]] = defaultdict(list)
    for n in nodes:
        cells[(n.lane_id, col[n.id])].append(n)
    rows: dict[str, float] = {
        lid: max([len(v) for (l2, _), v in cells.items() if l2 == lid], default=1) for lid, _ in lanes
    }

    min_x = ORIGIN_X + POOL_LABEL_W + 10
    for n in nodes:  # lanes grow to fit kept nodes
        if n.id in kept:
            h = SIZE.get(n.type, TASK_SIZE)[1]
            rows[n.lane_id] = max(rows[n.lane_id], (kept[n.id][2] + h + 20) / ROW_H)

    lane_tops: dict[str, float] = {}
    y = float(ORIGIN_Y)
    for lid, _ in lanes:
        lane_tops[lid] = y
        y += rows[lid] * ROW_H

    boxes: dict[str, Box] = {}
    for n in nodes:
        if n.id in kept:
            w, h = SIZE.get(n.type, TASK_SIZE)
            _, x, dy, _ = kept[n.id]
            boxes[n.id] = Box(max(x, min_x), lane_tops[n.lane_id] + max(dy, 0), w, h)

    forward = [f for f in flows if f.id not in back]
    preds: dict[str, list[str]] = defaultdict(list)
    succs: dict[str, list[str]] = defaultdict(list)
    for f in forward:
        preds[f.target_id].append(f.source_id)
        succs[f.source_id].append(f.target_id)

    def shift_downstream(start: str, delta: float) -> None:
        seen, stack = {start}, [start]
        while stack:
            nid = stack.pop()
            boxes[nid].x += delta
            for nxt in succs[nid]:
                if nxt in boxes and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)

    row_in_cell = {n.id: r for members in cells.values() for r, n in enumerate(members)}
    for n in sorted((n for n in nodes if n.id not in kept), key=lambda n: col[n.id]):
        w, h = SIZE.get(n.type, TASK_SIZE)
        cx = ORIGIN_X + POOL_LABEL_W + PAD_X + col[n.id] * COL_W + COL_W / 2
        cy = lane_tops[n.lane_id] + row_in_cell[n.id] * ROW_H + ROW_H / 2
        box = Box(cx - w / 2, cy - h / 2, w, h)
        placed = [boxes[p] for p in preds[n.id] if p in boxes]
        if kept and placed:  # follow the (possibly user-placed) predecessors, not the column grid
            box.x = max(b.x + b.w for b in placed) + GAP_X
        while any(_overlaps(box, boxes[o.id]) for o in nodes if o.id in boxes and o.lane_id == n.lane_id):
            box.x += COL_W
        boxes[n.id] = box
        for s in succs[n.id]:  # make room: push what comes after it to the right
            if s in kept and boxes[s].x < box.x + box.w + GAP_X:
                shift_downstream(s, box.x + box.w + GAP_X - boxes[s].x)

    right = max((b.x + b.w for b in boxes.values()), default=0)
    pool_w = max(POOL_LABEL_W + 2 * PAD_X + (max(col.values(), default=0) + 1) * COL_W, right + PAD_X - ORIGIN_X)
    lane_boxes = {
        lid: Box(ORIGIN_X + POOL_LABEL_W, lane_tops[lid], pool_w - POOL_LABEL_W, rows[lid] * ROW_H) for lid, _ in lanes
    }
    pool = Box(ORIGIN_X, ORIGIN_Y, pool_w, y - ORIGIN_Y)

    def unmoved(nid: str) -> bool:
        k = kept.get(nid)
        return k is not None and abs(boxes[nid].x - k[1]) < 0.5 and abs(boxes[nid].y - k[3]) < 0.5

    edges = {
        f.id: keep.edges[f.id]
        if f.id in keep.edges and unmoved(f.source_id) and unmoved(f.target_id)
        else _route(boxes[f.source_id], boxes[f.target_id])
        for f in flows
    }
    return Layout(pool, lane_boxes, boxes, edges)


def _overlaps(a: Box, b: Box, gap: float = 20) -> bool:
    return a.x < b.x + b.w + gap and b.x < a.x + a.w + gap and a.y < b.y + b.h + gap and b.y < a.y + a.h + gap


def _route(s: Box, t: Box) -> list[tuple[float, float]]:
    """Orthogonal waypoints. Targets to the left (loops, user-moved nodes) go underneath."""
    if t.x < s.x + s.w and s.x < t.x + t.w and (t.y >= s.y + s.h or s.y >= t.y + t.h):  # stacked vertically
        down = t.y >= s.y + s.h
        sy, ty = (s.y + s.h, t.y) if down else (s.y, t.y + t.h)
        mid = (sy + ty) / 2
        return [(s.cx, sy), (s.cx, mid), (t.cx, mid), (t.cx, ty)]
    if t.x < s.x + s.w:
        low = max(s.y + s.h, t.y + t.h) + 20
        return [(s.cx, s.y + s.h), (s.cx, low), (t.cx, low), (t.cx, t.y + t.h)]
    if abs(s.cy - t.cy) < 1:
        return [(s.x + s.w, s.cy), (t.x, t.cy)]
    mid = (s.x + s.w + t.x) / 2
    return [(s.x + s.w, s.cy), (mid, s.cy), (mid, t.cy), (t.x, t.cy)]


def to_bpmn(model: ProcessModel, keep: KeptPositions | None = None) -> bytes:
    lanes, nodes, flows = _clean(model)
    geo = layout(model, keep)

    defs = etree.Element(
        _q(BPMN, "definitions"),
        nsmap=NSMAP,
        id="Definitions_1",
        targetNamespace="http://bpmn.io/schema/bpmn",
        exporter="transcript2bpmn",
        exporterVersion="0.1.0",
    )
    collab = etree.SubElement(defs, _q(BPMN, "collaboration"), id="Collaboration_1")
    etree.SubElement(collab, _q(BPMN, "participant"), id="Participant_1", name=model.name, processRef="Process_1")
    proc = etree.SubElement(defs, _q(BPMN, "process"), id="Process_1", name=model.name, isExecutable="false")

    lane_set = etree.SubElement(proc, _q(BPMN, "laneSet"), id="LaneSet_1")
    for lid, name in lanes:
        lane = etree.SubElement(lane_set, _q(BPMN, "lane"), id=xml_id("Lane", lid), name=name)
        for n in nodes:
            if n.lane_id == lid:
                etree.SubElement(lane, _q(BPMN, "flowNodeRef")).text = xml_id("Node", n.id)

    for n in nodes:
        el = etree.SubElement(proc, _q(BPMN, TAG[n.type]), id=xml_id("Node", n.id), name=n.name)
        for f in flows:
            if f.target_id == n.id:
                etree.SubElement(el, _q(BPMN, "incoming")).text = xml_id("Flow", f.id)
        for f in flows:
            if f.source_id == n.id:
                etree.SubElement(el, _q(BPMN, "outgoing")).text = xml_id("Flow", f.id)

    for f in flows:
        attrs = {
            "id": xml_id("Flow", f.id),
            "sourceRef": xml_id("Node", f.source_id),
            "targetRef": xml_id("Node", f.target_id),
        }
        if f.condition:
            attrs["name"] = f.condition
        el = etree.SubElement(proc, _q(BPMN, "sequenceFlow"), attrs)
        if f.condition:
            expr = etree.SubElement(el, _q(BPMN, "conditionExpression"), {_q(XSI, "type"): "bpmn:tFormalExpression"})
            expr.text = f.condition

    diagram = etree.SubElement(defs, _q(BPMNDI, "BPMNDiagram"), id="BPMNDiagram_1")
    plane = etree.SubElement(diagram, _q(BPMNDI, "BPMNPlane"), id="BPMNPlane_1", bpmnElement="Collaboration_1")

    def shape(element_id: str, box: Box, horizontal: bool = False) -> None:
        attrs = {"id": f"{element_id}_di", "bpmnElement": element_id}
        if horizontal:
            attrs["isHorizontal"] = "true"
        sh = etree.SubElement(plane, _q(BPMNDI, "BPMNShape"), attrs)
        etree.SubElement(sh, _q(DC, "Bounds"), x=_n(box.x), y=_n(box.y), width=_n(box.w), height=_n(box.h))

    shape("Participant_1", geo.pool, horizontal=True)
    for lid, _ in lanes:
        shape(xml_id("Lane", lid), geo.lanes[lid], horizontal=True)
    for n in nodes:
        shape(xml_id("Node", n.id), geo.nodes[n.id])
    for f in flows:
        fid = xml_id("Flow", f.id)
        edge = etree.SubElement(plane, _q(BPMNDI, "BPMNEdge"), id=f"{fid}_di", bpmnElement=fid)
        for x, y in geo.edges[f.id]:
            etree.SubElement(edge, _q(DI, "waypoint"), x=_n(x), y=_n(y))

    return etree.tostring(defs, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _n(v: float) -> str:
    return str(round(v))


@lru_cache
def _schema() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(XSD)))


class InvalidBPMN(ValueError):
    pass


def validate_xsd(xml: bytes) -> None:
    schema = _schema()
    if not schema.validate(etree.fromstring(xml)):
        raise InvalidBPMN(str(schema.error_log))
