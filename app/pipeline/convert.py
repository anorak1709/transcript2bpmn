"""ProcessModel -> BPMN 2.0 XML (semantic model + diagram layout). Deterministic, no LLM.

Layout: bpmn-auto-layout (bpmn-io) was evaluated and rejected; it only lays out the first
participant and has no lane placement (lanes get a default size, nodes ignore them).
So: x = column from longest-path layering over the flow DAG (back edges ignored),
y = lane band, with sub-rows when several nodes of one lane share a column.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
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
    """Make the model drawable: unknown lanes -> 'Unassigned', dangling flows dropped.

    Real validation + repair is Phase 3; this only guarantees well-formed output.
    """
    lanes = [(lane.id, lane.name) for lane in model.lanes]
    lane_ids = {lid for lid, _ in lanes}
    nodes = [n if n.lane_id in lane_ids else n.model_copy(update={"lane_id": UNASSIGNED_LANE}) for n in model.nodes]
    if any(n.lane_id == UNASSIGNED_LANE for n in nodes):
        lanes.append((UNASSIGNED_LANE, "Unassigned"))
    node_ids = {n.id for n in nodes}
    flows = [f for f in model.flows if f.source_id in node_ids and f.target_id in node_ids]
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


def layout(model: ProcessModel) -> Layout:
    lanes, nodes, flows = _clean(model)
    col, back = _columns(nodes, flows)

    cells: dict[tuple[str, int], list[Node]] = defaultdict(list)
    for n in nodes:
        cells[(n.lane_id, col[n.id])].append(n)
    rows = {lid: max([len(v) for (l2, _), v in cells.items() if l2 == lid], default=1) for lid, _ in lanes}

    ncols = max(col.values(), default=0) + 1
    pool_w = POOL_LABEL_W + 2 * PAD_X + ncols * COL_W
    lane_boxes: dict[str, Box] = {}
    y = float(ORIGIN_Y)
    for lid, _ in lanes:
        h = rows[lid] * ROW_H
        lane_boxes[lid] = Box(ORIGIN_X + POOL_LABEL_W, y, pool_w - POOL_LABEL_W, h)
        y += h
    pool = Box(ORIGIN_X, ORIGIN_Y, pool_w, y - ORIGIN_Y)

    boxes: dict[str, Box] = {}
    for (lid, c), members in cells.items():
        for row, n in enumerate(members):
            w, h = SIZE.get(n.type, TASK_SIZE)
            cx = ORIGIN_X + POOL_LABEL_W + PAD_X + c * COL_W + COL_W / 2
            cy = lane_boxes[lid].y + row * ROW_H + ROW_H / 2
            boxes[n.id] = Box(cx - w / 2, cy - h / 2, w, h)

    edges: dict[str, list[tuple[float, float]]] = {}
    for f in flows:
        s, t = boxes[f.source_id], boxes[f.target_id]
        if f.id in back:  # loop back underneath
            low = max(s.y + s.h, t.y + t.h) + 20
            edges[f.id] = [(s.cx, s.y + s.h), (s.cx, low), (t.cx, low), (t.cx, t.y + t.h)]
        elif abs(s.cy - t.cy) < 1:
            edges[f.id] = [(s.x + s.w, s.cy), (t.x, t.cy)]
        else:
            mid = (s.x + s.w + t.x) / 2
            edges[f.id] = [(s.x + s.w, s.cy), (mid, s.cy), (mid, t.cy), (t.x, t.cy)]
    return Layout(pool, lane_boxes, boxes, edges)


def to_bpmn(model: ProcessModel) -> bytes:
    lanes, nodes, flows = _clean(model)
    geo = layout(model)

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
