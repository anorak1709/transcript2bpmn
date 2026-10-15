from typing import Any

import pytest
from lxml import etree

from app.models.process import ProcessModel
from app.pipeline.convert import DI, layout, to_bpmn, validate_xsd
from app.pipeline.edit import EditPlan, OpError, PatchOp, apply_ops, plan_edit
from app.pipeline.parse_bpmn import NS, read_bpmn
from app.pipeline.validate import validate
from tests.conftest import gold_model
from tests.test_validate import ScriptedLLM


def ops(*raw: dict[str, Any]) -> list[PatchOp]:
    return EditPlan.model_validate({"ops": list(raw), "reply": ""}).ops


def edges(m: ProcessModel) -> set[tuple[str, str]]:
    return {(f.source_id, f.target_id) for f in m.flows}


@pytest.fixture
def invoice() -> ProcessModel:
    return gold_model("01_invoice_approval")


def test_add_task_inserted_after_takes_over_outgoing_flows(invoice: ProcessModel) -> None:
    m = apply_ops(
        invoice,
        ops(
            {
                "op": "add_task",
                "id": "t_scan",
                "name": "Scan invoice",
                "type": "user_task",
                "lane_id": "lane_ap",
                "insert_after": "t_enter",
            }
        ),
    )
    assert ("t_enter", "t_scan") in edges(m) and ("t_scan", "t_match") in edges(m)
    assert ("t_enter", "t_match") not in edges(m)
    new = next(n for n in m.nodes if n.id == "t_scan")
    assert new.user_added and new.confidence == 1.0 and new.source_segment_ids == []
    assert validate(m) == []
    assert invoice.nodes[-1].id != "t_scan"  # original untouched


def test_new_ids_never_collide_and_later_ops_follow_the_rename(invoice: ProcessModel) -> None:
    m = apply_ops(
        invoice,
        ops(
            {
                "op": "add_task",
                "id": "t_pay",
                "name": "Notify supplier",
                "type": "service_task",
                "lane_id": "lane_fin",
                "insert_after": None,
            },
            {"op": "connect", "source_id": "t_pay", "target_id": "end_paid", "condition": None},
        ),
    )
    new = next(n for n in m.nodes if n.name == "Notify supplier")
    assert new.id == "t_pay_2"
    assert ("t_pay_2", "end_paid") in edges(m)


def test_remove_node_with_and_without_reconnect(invoice: ProcessModel) -> None:
    m = apply_ops(invoice, ops({"op": "remove_node", "node_id": "t_match", "reconnect": True}))
    assert ("t_enter", "g_match") in edges(m) and validate(m) == []
    m = apply_ops(invoice, ops({"op": "remove_node", "node_id": "t_match", "reconnect": False}))
    assert {e.code for e in validate(m)} >= {"DEAD_END", "UNREACHABLE"}


def test_rename_reassign_add_lane(invoice: ProcessModel) -> None:
    m = apply_ops(
        invoice,
        ops(
            {"op": "add_lane", "id": "lane_treasury", "name": "Treasury"},
            {"op": "reassign_lane", "node_id": "t_pay", "lane_id": "lane_treasury"},
            {"op": "rename_node", "node_id": "t_pay", "name": "Release payment"},
        ),
    )
    pay = next(n for n in m.nodes if n.id == "t_pay")
    assert (pay.lane_id, pay.name) == ("lane_treasury", "Release payment")
    assert m.lanes[-1].name == "Treasury"


def test_merge_tasks(invoice: ProcessModel) -> None:
    m = apply_ops(invoice, ops({"op": "merge_tasks", "node_ids": ["t_enter", "t_match"], "name": "Enter and match"}))
    assert "t_match" not in {n.id for n in m.nodes}
    assert ("t_enter", "g_match") in edges(m) and ("t_enter", "t_enter") not in edges(m)
    assert validate(m) == []
    with pytest.raises(OpError, match="2\\+ task"):
        apply_ops(invoice, ops({"op": "merge_tasks", "node_ids": ["t_enter", "g_match"], "name": "x"}))


def test_split_task(invoice: ProcessModel) -> None:
    m = apply_ops(invoice, ops({"op": "split_task", "node_id": "t_pay", "names": ["Schedule payment", "Pay supplier"]}))
    assert ("t_pay", "t_pay_2") in edges(m) and ("t_pay_2", "end_paid") in edges(m)
    second = next(n for n in m.nodes if n.id == "t_pay_2")
    assert second.source_segment_ids == ["s4"] and not second.user_added  # inherits the evidence
    assert validate(m) == []


def test_gateway_connect_conditions_disconnect(invoice: ProcessModel) -> None:
    m = apply_ops(
        invoice,
        ops(
            {
                "op": "add_gateway",
                "id": "g_risk",
                "type": "exclusive_gateway",
                "name": "High risk?",
                "lane_id": "lane_fin",
                "insert_after": "t_fin_approve",
            },
            {"op": "set_condition", "source_id": "g_risk", "target_id": "g_join", "condition": "No"},
            {
                "op": "add_task",
                "id": "t_cfo",
                "name": "Get CFO sign-off",
                "type": "user_task",
                "lane_id": "lane_fin",
                "insert_after": None,
            },
            {"op": "connect", "source_id": "g_risk", "target_id": "t_cfo", "condition": "Yes"},
            {"op": "connect", "source_id": "t_cfo", "target_id": "g_join", "condition": None},
        ),
    )
    assert validate(m) == []
    m2 = apply_ops(m, ops({"op": "disconnect", "source_id": "t_cfo", "target_id": "g_join"}))
    assert "DEAD_END" in {e.code for e in validate(m2)}


def test_resolve_open_question() -> None:
    m = gold_model("02_employee_onboarding")
    assert apply_ops(m, ops({"op": "resolve_open_question", "question_id": "q1"})).open_questions == []


def test_ops_are_all_or_nothing(invoice: ProcessModel) -> None:
    with pytest.raises(OpError, match="op 2 \\(rename_node\\): no node 'ghost'"):
        apply_ops(
            invoice,
            ops(
                {"op": "rename_node", "node_id": "t_pay", "name": "Changed"},
                {"op": "rename_node", "node_id": "ghost", "name": "x"},
            ),
        )
    assert next(n for n in invoice.nodes if n.id == "t_pay").name == "Pay supplier in weekly payment run"


def test_plan_edit_retries_once_with_the_error(invoice: ProcessModel) -> None:
    bad = EditPlan.model_validate({"ops": [{"op": "rename_node", "node_id": "pay", "name": "Pay"}], "reply": "x"})
    good = EditPlan.model_validate({"ops": [{"op": "rename_node", "node_id": "t_pay", "name": "Pay"}], "reply": "Done"})
    llm = ScriptedLLM(bad, good)
    model, plan = plan_edit(llm, invoice, "call the payment step Pay")
    assert plan.reply == "Done" and next(n for n in model.nodes if n.id == "t_pay").name == "Pay"
    assert llm.calls[0]["role"] == "edit" and "no node 'pay'" in llm.calls[1]["input"]

    with pytest.raises(OpError):
        plan_edit(ScriptedLLM(bad, bad), invoice, "x")


def _drag(model: ProcessModel, node_xml_id: str, x: float) -> bytes:
    """Simulate the user dragging a node in the editor."""
    root = etree.fromstring(to_bpmn(model))
    bounds = root.find(f".//bpmndi:BPMNShape[@bpmnElement='{node_xml_id}']/dc:Bounds", NS)
    assert bounds is not None
    bounds.set("x", str(x))
    return etree.tostring(root)


def test_insertion_reflows_downstream_and_keeps_upstream(invoice: ProcessModel) -> None:
    _, keep = read_bpmn(_drag(invoice, "Node_t_pay", 1500), invoice)
    before = layout(invoice, keep)
    edited = apply_ops(
        invoice,
        ops(
            {
                "op": "add_task",
                "id": "t_scan",
                "name": "Scan",
                "type": "user_task",
                "lane_id": "lane_ap",
                "insert_after": "t_enter",
            }
        ),
    )
    geo = layout(edited, keep)

    for upstream in ("start", "t_enter"):  # before the insertion: untouched
        assert (geo.nodes[upstream].x, geo.nodes[upstream].y) == (before.nodes[upstream].x, before.nodes[upstream].y)
    enter, scan, match = geo.nodes["t_enter"], geo.nodes["t_scan"], geo.nodes["t_match"]
    assert enter.x + enter.w < scan.x < scan.x + scan.w < match.x  # inserted in order, left to right
    delta = geo.nodes["t_match"].x - before.nodes["t_match"].x
    assert delta > 0
    for downstream in ("t_match", "g_match", "t_pay", "end_paid"):  # shifted together: arrangement kept
        assert geo.nodes[downstream].x - before.nodes[downstream].x == delta
    assert geo.nodes["t_pay"].x == 1500 + delta  # the user's drag survives, just shifted with its neighbours
    others = [b for nid, b in geo.nodes.items() if nid != "t_scan"]
    assert not any(
        scan.x < b.x + b.w and b.x < scan.x + scan.w and scan.y < b.y + b.h and b.y < scan.y + scan.h for b in others
    )
    validate_xsd(to_bpmn(edited, keep))


def test_unrelated_edit_keeps_every_position_and_hand_drawn_route(invoice: ProcessModel) -> None:
    root = etree.fromstring(_drag(invoice, "Node_t_pay", 1500))
    edge = root.find(".//bpmndi:BPMNEdge[@bpmnElement='Flow_f12']", NS)
    assert edge is not None
    for w in list(edge):
        edge.remove(w)
    custom = [(1600, 380), (1600, 460), (1700, 460), (1700, 400)]  # a detour the user drew
    for x, y in custom:
        etree.SubElement(edge, f"{{{DI}}}waypoint", x=str(x), y=str(y))
    _, keep = read_bpmn(etree.tostring(root), invoice)

    renamed = apply_ops(invoice, ops({"op": "rename_node", "node_id": "t_match", "name": "Three-way match"}))
    before, after = layout(invoice, keep), layout(renamed, keep)
    assert {k: (b.x, b.y) for k, b in after.nodes.items()} == {k: (b.x, b.y) for k, b in before.nodes.items()}
    assert after.edges["f12"] == custom
    # ...but once an endpoint moves, the stale route is recomputed instead of kept.
    moved = apply_ops(
        invoice,
        ops(
            {
                "op": "add_task",
                "id": "t_x",
                "name": "X",
                "type": "service_task",
                "lane_id": "lane_fin",
                "insert_after": "g_join",
            }
        ),
    )
    assert layout(moved, keep).edges["f12"] != custom
