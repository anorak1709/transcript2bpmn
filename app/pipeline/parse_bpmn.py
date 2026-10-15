"""BPMN XML (e.g. saved from the bpmn-js editor) -> ProcessModel + node positions.

Elements are matched to the current model by id: our exports use `Node_<id>` / `Lane_<id>`
/ `Flow_<id>`. Anything the editor created (bpmn-js ids like `Activity_0x1y`) is new:
it keeps its editor id, gets no transcript citations, confidence 1.0, user_added=True.
"""

from lxml import etree

from app.models.process import Flow, Lane, Node, NodeType, OpenQuestion, ProcessModel
from app.pipeline.convert import BPMN, BPMNDI, DC, DI, UNASSIGNED_LANE, KeptPositions

NS = {"bpmn": BPMN, "bpmndi": BPMNDI, "dc": DC, "di": DI}

NODE_TYPES: dict[str, NodeType] = {
    "startEvent": "start_event",
    "endEvent": "end_event",
    "task": "user_task",
    "userTask": "user_task",
    "manualTask": "user_task",
    "serviceTask": "service_task",
    "scriptTask": "service_task",
    "businessRuleTask": "service_task",
    "sendTask": "service_task",
    "receiveTask": "service_task",
    "exclusiveGateway": "exclusive_gateway",
    "parallelGateway": "parallel_gateway",
}
# Flow nodes the ProcessModel can't represent. Rejected rather than silently dropped.
UNSUPPORTED = {
    "intermediateCatchEvent",
    "intermediateThrowEvent",
    "boundaryEvent",
    "subProcess",
    "transaction",
    "callActivity",
    "adHocSubProcess",
    "inclusiveGateway",
    "eventBasedGateway",
    "complexGateway",
}

# No entity expansion, no network, no DTD: this parses user-supplied XML (XXE / billion laughs).
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, remove_comments=True)


class BpmnImportError(ValueError):
    pass


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname


def _match(xml_id: str, prefix: str, known: set[str]) -> str:
    """Map an XML id back to a model id: `Node_t1` -> `t1` if t1 exists, else keep as-is (new)."""
    stripped = xml_id.removeprefix(f"{prefix}_")
    if stripped != xml_id and stripped in known:
        return stripped
    return xml_id


def read_bpmn(xml: bytes, current: ProcessModel) -> tuple[ProcessModel, KeptPositions]:
    try:
        root = etree.fromstring(xml, _PARSER)
    except etree.XMLSyntaxError as e:
        raise BpmnImportError(f"Not well-formed XML: {e}") from e
    if root.tag != f"{{{BPMN}}}definitions":
        raise BpmnImportError("Not a BPMN 2.0 document (root must be bpmn:definitions)")

    processes = [p for p in root.iterfind("bpmn:process", NS) if any(_local(c) in NODE_TYPES for c in p)]
    if len(processes) > 1:
        raise BpmnImportError("Only one pool/process is supported")
    process = processes[0] if processes else root.find("bpmn:process", NS)
    if process is None:
        raise BpmnImportError("No bpmn:process found")

    unsupported = sorted({_local(c) for c in process if _local(c) in UNSUPPORTED})
    if unsupported:
        raise BpmnImportError(f"Unsupported BPMN elements: {', '.join(unsupported)}")

    old_nodes = {n.id: n for n in current.nodes}
    lane_names = {lane.id: lane.name for lane in current.lanes}

    lanes: list[Lane] = []
    lane_of: dict[str, str] = {}  # xml node id -> model lane id (deepest lane wins)
    xml_lane: dict[str, str] = {}  # model lane id -> xml lane id
    for el in process.iterfind(".//bpmn:lane", NS):
        lid = _match(el.get("id", ""), "Lane", set(lane_names))
        lanes.append(Lane(id=lid, name=el.get("name") or lane_names.get(lid, "")))
        xml_lane[lid] = el.get("id", "")
        for ref in el.iterfind("bpmn:flowNodeRef", NS):
            lane_of[(ref.text or "").strip()] = lid

    nodes: list[Node] = []
    node_id: dict[str, str] = {}  # xml id -> model id
    for el in process:
        kind = NODE_TYPES.get(_local(el))
        if kind is None:
            continue
        xid = el.get("id", "")
        nid = _match(xid, "Node", set(old_nodes))
        node_id[xid] = nid
        lane = lane_of.get(xid, UNASSIGNED_LANE)
        old = old_nodes.get(nid)
        nodes.append(
            Node(
                id=nid,
                type=kind,
                name=el.get("name") or "",
                lane_id=lane,
                source_segment_ids=old.source_segment_ids if old else [],
                confidence=old.confidence if old else 1.0,
                user_added=old.user_added if old else True,
            )
        )
    if any(n.lane_id == UNASSIGNED_LANE for n in nodes) and UNASSIGNED_LANE not in {lane.id for lane in lanes}:
        lanes.append(Lane(id=UNASSIGNED_LANE, name="Unassigned"))

    old_flows = {f.id for f in current.flows}
    exclusive = {node_id[el.get("id", "")] for el in process if _local(el) == "exclusiveGateway"}
    flows: list[Flow] = []
    flow_id: dict[str, str] = {}  # xml id -> model id
    for el in process.iterfind("bpmn:sequenceFlow", NS):
        src, tgt = node_id.get(el.get("sourceRef", "")), node_id.get(el.get("targetRef", ""))
        if src is None or tgt is None:
            continue  # e.g. connected to a dropped artifact; validation would flag the gap
        cond = (el.findtext("bpmn:conditionExpression", namespaces=NS) or "").strip()
        if not cond and src in exclusive:
            cond = (el.get("name") or "").strip()  # bpmn-js users label decision paths by name
        fid = _match(el.get("id", ""), "Flow", old_flows)
        flow_id[el.get("id", "")] = fid
        flows.append(Flow(id=fid, source_id=src, target_id=tgt, condition=cond or None))

    kept = set(node_id.values())
    questions = [
        OpenQuestion(
            id=q.id,
            question=q.question,
            related_node_ids=[r for r in q.related_node_ids if r in kept],
            source_segment_ids=q.source_segment_ids,
        )
        for q in current.open_questions
    ]
    participant = root.find("bpmn:collaboration/bpmn:participant", NS)
    name = (participant.get("name") if participant is not None else None) or process.get("name") or current.name
    model = ProcessModel(name=name, lanes=lanes, nodes=nodes, flows=flows, open_questions=questions)
    return model, _positions(root, node_id, lane_of, xml_lane, flow_id)


def _positions(
    root: etree._Element,
    node_id: dict[str, str],
    lane_of: dict[str, str],
    xml_lane: dict[str, str],
    flow_id: dict[str, str],
) -> KeptPositions:
    bounds: dict[str, tuple[float, float]] = {}
    for shape in root.iterfind(".//bpmndi:BPMNShape", NS):
        b = shape.find("dc:Bounds", NS)
        if b is not None:
            bounds[shape.get("bpmnElement", "")] = (float(b.get("x", 0)), float(b.get("y", 0)))
    out = KeptPositions()
    for xid, nid in node_id.items():
        lane = lane_of.get(xid)
        if lane is None or xid not in bounds or xml_lane.get(lane) not in bounds:
            continue
        x, y = bounds[xid]
        out.nodes[nid] = (lane, x, y - bounds[xml_lane[lane]][1], y)
    for edge in root.iterfind(".//bpmndi:BPMNEdge", NS):
        fid = flow_id.get(edge.get("bpmnElement", ""))
        points = [(float(w.get("x", 0)), float(w.get("y", 0))) for w in edge.iterfind("di:waypoint", NS)]
        if fid and len(points) >= 2:
            out.edges[fid] = points
    return out
