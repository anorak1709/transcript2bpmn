"""generate -> edit visually -> save -> chat edit -> undo, every step XSD-valid.

Needs the compose services (see test_integration.py). The visual edit is real bpmn-js
output: tests/fixtures/bpmnjs_edited_invoice.bpmn was produced by the bpmn-js Modeler
(adding a task, connecting it, renaming, moving, relabelling a path) and saved with saveXML.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.maps import get_llm
from app.main import app
from app.pipeline.convert import validate_xsd
from app.pipeline.edit import EditPlan
from tests.conftest import GOLD, FakeLLM, TenantCtx, gold_model, needs_services
from tests.test_validate import ScriptedLLM

pytestmark = needs_services
EDITED = Path(__file__).parent / "fixtures" / "bpmnjs_edited_invoice.bpmn"


@pytest.fixture
def client(tenant: TenantCtx) -> Iterator[TestClient]:
    yield tenant.client
    app.dependency_overrides.clear()


@pytest.fixture
def map_id(tenant: TenantCtx) -> str:
    vtt = (GOLD / "01_invoice_approval" / "transcript.vtt").read_bytes()
    tid = tenant.upload("w.vtt", vtt).json()["id"]
    mid: str = tenant.process(tid, FakeLLM(gold_model("01_invoice_approval")))["map_id"]
    return mid


def _valid(m: dict[str, Any]) -> dict[str, Any]:
    validate_xsd(m["bpmn_xml"].encode())
    return m


def _node(m: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(n for n in m["model"]["nodes"] if n["id"] == node_id)


def _bounds(m: dict[str, Any], xml_id: str) -> str:
    xml: str = m["bpmn_xml"]
    i = xml.index(f'bpmnElement="{xml_id}"')
    return xml[xml.index("<dc:Bounds", i) : xml.index("/>", xml.index("<dc:Bounds", i))]


def test_full_round_trip(client: TestClient, map_id: str) -> None:
    v1 = _valid(client.get(f"/maps/{map_id}").json())
    assert (v1["version"], v1["can_undo"], v1["errors"]) == (1, False, [])
    assert {s["segment_id"] for s in v1["segments"]} == {"s1", "s2", "s3", "s4"}  # quotes available to the UI

    # Visual edit saved from bpmn-js.
    r = client.put(f"/maps/{map_id}/bpmn", content=EDITED.read_bytes(), headers={"Content-Type": "application/xml"})
    assert r.status_code == 200, r.text
    v2 = _valid(r.json())
    assert v2["version"] == 2 and v2["errors"] == []
    scan = _node(v2, "Activity_0gufld4")
    assert (scan["name"], scan["user_added"], scan["source_segment_ids"], scan["confidence"]) == (
        "Scan invoice",
        True,
        [],
        1.0,
    )
    assert _node(v2, "t_pay")["name"] == "Release payment" and _node(v2, "t_pay")["source_segment_ids"] == ["s4"]
    start_v2 = _bounds(v2, "Node_start")
    assert start_v2 != _bounds(v1, "Node_start")  # the drag was kept

    # Chat edit on top of the visual edit.
    plan = EditPlan.model_validate(
        {
            "reply": "Added a duplicate check.",
            "ops": [
                {
                    "op": "add_task",
                    "id": "t_dupe",
                    "name": "Check for duplicate invoice",
                    "type": "user_task",
                    "lane_id": "lane_ap",
                    "insert_after": "Activity_0gufld4",
                },
            ],
        }
    )
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(plan)
    r = client.post(f"/maps/{map_id}/chat", json={"instruction": "check for duplicates after scanning"})
    assert r.status_code == 200, r.text
    v3 = _valid(r.json())
    assert v3["version"] == 3 and v3["reply"] == "Added a duplicate check." and v3["ops"][0]["op"] == "add_task"
    assert _node(v3, "t_dupe")["user_added"] and v3["errors"] == []
    assert _bounds(v3, "Node_start") == start_v2  # untouched node kept its manual position

    # Undo back through the history.
    u2 = _valid(client.post(f"/maps/{map_id}/undo").json())
    assert u2["version"] == 2 and u2["model"] == v2["model"] and u2["bpmn_xml"] == v2["bpmn_xml"]
    u1 = _valid(client.post(f"/maps/{map_id}/undo").json())
    assert u1["version"] == 1 and u1["model"] == v1["model"] and not u1["can_undo"]
    assert client.post(f"/maps/{map_id}/undo").status_code == 409

    # A new edit after undoing replaces the undone branch.
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(
        plan.model_copy(
            update={
                "ops": [
                    EditPlan.model_validate(
                        {
                            "reply": "",
                            "ops": [{"op": "rename_node", "node_id": "t_enter", "name": "Key invoice into ERP"}],
                        }
                    ).ops[0]
                ]
            }
        )
    )
    v2b = _valid(client.post(f"/maps/{map_id}/chat", json={"instruction": "rename"}).json())
    assert v2b["version"] == 2
    history = client.get(f"/maps/{map_id}/versions").json()
    assert [(h["version"], h["source"]) for h in history] == [(1, "extract"), (2, "chat")]
    assert history[1]["instruction"] == "rename"


def test_chat_edit_errors(client: TestClient, map_id: str) -> None:
    bad = EditPlan.model_validate({"reply": "", "ops": [{"op": "rename_node", "node_id": "nope", "name": "x"}]})
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(bad, bad)
    r = client.post(f"/maps/{map_id}/chat", json={"instruction": "rename nope"})
    assert r.status_code == 422 and "no node 'nope'" in r.json()["detail"]

    question = EditPlan.model_validate({"reply": "Which approval step do you mean?", "ops": []})
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(question)
    r = client.post(f"/maps/{map_id}/chat", json={"instruction": "change the approval"})
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["reply"].startswith("Which")


def test_bad_bpmn_uploads_are_rejected(client: TestClient, map_id: str) -> None:
    def put(body: bytes) -> Any:
        return client.put(f"/maps/{map_id}/bpmn", content=body, headers={"Content-Type": "application/xml"})

    assert put(b"<not-xml").status_code == 422
    assert put(b"<root/>").status_code == 422
    sub = EDITED.read_bytes().replace(b"<bpmn:task ", b'<bpmn:subProcess id="Sub_1" />\n    <bpmn:task ', 1)
    r = put(sub)
    assert r.status_code == 422 and "subProcess" in r.json()["detail"]
    # XXE: an external entity must not be resolved into the model.
    xxe = (
        EDITED.read_bytes()
        .replace(
            b'<?xml version="1.0" encoding="UTF-8"?>',
            b'<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>',
        )
        .replace(b'name="Scan invoice"', b'name="&x;"')
    )
    r = put(xxe)
    assert r.status_code == 422 and "external entity" in r.json()["detail"] and "root:" not in r.text
    assert client.get(f"/maps/{map_id}").json()["version"] == 1  # nothing was stored
