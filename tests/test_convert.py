"""Converter tests: fixed ProcessModel fixtures, no LLM."""

import pytest
from lxml import etree

from app.models.process import Flow, Lane, Node, ProcessModel
from app.pipeline.convert import BPMN, BPMNDI, DC, InvalidBPMN, layout, to_bpmn, validate_xsd
from tests.conftest import gold_model

NS = {"bpmn": BPMN, "bpmndi": BPMNDI, "dc": DC}


def _node(id: str, type: str = "user_task", lane: str = "l1") -> Node:
    return Node(id=id, type=type, name=id, lane_id=lane, source_segment_ids=["s1"], confidence=1)


def _flow(src: str, tgt: str, cond: str | None = None) -> Flow:
    return Flow(id=f"{src}-{tgt}", source_id=src, target_id=tgt, condition=cond)


@pytest.mark.parametrize("case", ["01_invoice_approval", "02_employee_onboarding"])
def test_gold_models_produce_xsd_valid_bpmn(case: str) -> None:
    model = gold_model(case)
    xml = to_bpmn(model)
    validate_xsd(xml)  # raises on failure

    root = etree.fromstring(xml)
    proc = root.find("bpmn:process", NS)
    assert proc is not None
    # Every node is in exactly one lane, and every node/flow has a diagram element.
    refs = [r.text or "" for r in proc.iterfind("bpmn:laneSet/bpmn:lane/bpmn:flowNodeRef", NS)]
    assert sorted(refs) == sorted(f"Node_{n.id}" for n in model.nodes)
    di_refs = {e.get("bpmnElement") for e in root.iterfind(".//bpmndi:BPMNShape", NS)}
    di_refs |= {e.get("bpmnElement") for e in root.iterfind(".//bpmndi:BPMNEdge", NS)}
    assert {f"Node_{n.id}" for n in model.nodes} | {f"Flow_{f.id}" for f in model.flows} <= di_refs


def test_conditions_become_condition_expressions() -> None:
    root = etree.fromstring(to_bpmn(gold_model("01_invoice_approval")))
    flow = root.find(".//bpmn:sequenceFlow[@id='Flow_f7']", NS)
    assert flow is not None and flow.get("name") == "Over $5,000"
    assert flow.findtext("bpmn:conditionExpression", namespaces=NS) == "Over $5,000"
    assert root.find(".//bpmn:sequenceFlow[@id='Flow_f1']/bpmn:conditionExpression", NS) is None


def test_nodes_sit_inside_their_lane_and_flow_left_to_right() -> None:
    model = gold_model("01_invoice_approval")
    geo = layout(model)
    for n in model.nodes:
        box, lane = geo.nodes[n.id], geo.lanes[n.lane_id]
        assert lane.y <= box.y and box.y + box.h <= lane.y + lane.h, n.id
    assert geo.nodes["start"].x < geo.nodes["t_enter"].x < geo.nodes["g_match"].x < geo.nodes["t_pay"].x
    # Lanes stack without overlap inside the pool.
    ys = sorted((b.y, b.y + b.h) for b in geo.lanes.values())
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(ys, ys[1:], strict=False))


def test_unsafe_ids_unknown_lane_dangling_flow_and_cycle() -> None:
    model = ProcessModel(
        name="Messy",
        lanes=[Lane(id="l1", name="Team")],
        nodes=[
            _node("1 start", "start_event"),
            _node("2"),
            _node("3", lane="ghost"),  # lane doesn't exist
            _node("g", "exclusive_gateway"),
            _node("end", "end_event"),
        ],
        flows=[
            _flow("1 start", "2"),
            _flow("2", "3"),
            _flow("3", "g"),
            _flow("g", "2", "Rework"),  # loop back
            _flow("g", "end", "OK"),
            _flow("g", "missing"),  # dangling
        ],
        open_questions=[],
    )
    xml = to_bpmn(model)
    validate_xsd(xml)
    root = etree.fromstring(xml)
    assert root.find(".//bpmn:startEvent[@id='Node_1_start']", NS) is not None
    assert root.find(".//bpmn:lane[@name='Unassigned']/bpmn:flowNodeRef", NS).text == "Node_3"  # type: ignore[union-attr]
    assert root.find(".//bpmn:sequenceFlow[@targetRef='Node_missing']", NS) is None


def test_xsd_actually_rejects_invalid_bpmn() -> None:
    bad = to_bpmn(gold_model("02_employee_onboarding")).replace(b'sourceRef="Node_start"', b"")
    with pytest.raises(InvalidBPMN, match="sourceRef"):
        validate_xsd(bad)
