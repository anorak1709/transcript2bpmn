"""Speaker roles, evidence, gaps, variants, the agenda, policy comparison and sign-off, through
the API with the fake LLM (no provider calls)."""

from typing import Any

from app.models.process import ProcessModel
from tests.conftest import FakeLLM, TenantCtx, make_tenant, needs_services
from tests.test_projects import CASE, merged_project

pytestmark = needs_services


def conflicts(t: TenantCtx, **params: str) -> list[dict[str, Any]]:
    r = t.client.get(f"/projects/{t.project_id}/conflicts", params=params)
    assert r.status_code == 200, r.text
    return list(r.json())


def version(t: TenantCtx, map_id: str) -> int:
    return int(t.client.get(f"/maps/{map_id}").json()["version"])


def test_speaker_roles_weight_the_evidence(tenant: TenantCtx) -> None:
    merged_project(tenant)
    speakers = tenant.client.get(f"/projects/{tenant.project_id}/speakers").json()
    assert {s["name"] for s in speakers} == {"Priya", "Marco", "Sana"}
    assert all(s["role"] is None and s["lines"] > 0 for s in speakers)

    r = tenant.client.put(f"/projects/{tenant.project_id}/speakers/Sana", json={"role": "owner"})
    assert r.status_code == 200 and r.json()["role"] == "owner"
    assert (
        tenant.client.put(f"/projects/{tenant.project_id}/speakers/Nobody", json={"role": "owner"}).status_code == 404
    )

    owner = next(c for c in conflicts(tenant) if c["kind"] == "owner")
    finance, treasury = owner["sides"]
    assert finance["label"] == "Finance" and treasury["label"] == "Treasury"
    assert {q["speaker"] for q in finance["quotes"]} == {"Marco"}
    assert [(q["speaker"], q["role"]) for q in treasury["quotes"]] == [("Sana", "owner")]
    assert "treasury pays the supplier" in treasury["quotes"][0]["text"]
    assert owner["owner_side"] == 1  # only Treasury's side has the process owner on it

    tenant.client.put(f"/projects/{tenant.project_id}/speakers/Marco", json={"role": "owner"})
    owner = next(c for c in conflicts(tenant) if c["kind"] == "owner")
    assert owner["owner_side"] is None  # both sides have an owner: no hint


def test_gaps_can_be_dismissed(tenant: TenantCtx) -> None:
    merged_project(tenant)
    gaps = tenant.client.get(f"/projects/{tenant.project_id}/gaps").json()
    assert {g["kind"] for g in gaps} == {"no_exception"}
    assert any("Approve invoice (finance)" in g["question"] for g in gaps)
    gid = gaps[0]["id"]
    assert tenant.client.post(f"/projects/{tenant.project_id}/gaps/{gid}/dismiss").status_code == 200
    assert gid not in {g["id"] for g in tenant.client.get(f"/projects/{tenant.project_id}/gaps").json()}
    assert tenant.client.post(f"/projects/{tenant.project_id}/gaps/{gid}/dismiss").status_code == 404


def test_both_are_true_adds_a_labelled_decision(tenant: TenantCtx) -> None:
    ctx = merged_project(tenant)
    mid = ctx["merged_map_id"]
    owner = next(c for c in conflicts(tenant) if c["kind"] == "owner")
    v = version(tenant, mid)

    bad = {"variant": {"question": "Which region?", "labels": ["North"]}}
    assert (
        tenant.client.post(f"/conflicts/{owner['id']}/resolve", json=bad, headers={"If-Match": f'"{v}"'}).status_code
        == 422
    )
    both = {"option": 1, "variant": {"question": "Which region?", "labels": ["North", "South"]}}
    assert tenant.client.post(f"/conflicts/{owner['id']}/resolve", json=both).status_code == 400

    body = {"variant": {"question": "Which region?", "labels": ["North", "South"]}}
    r = tenant.client.post(f"/conflicts/{owner['id']}/resolve", json=body, headers={"If-Match": f'"{v}"'})
    assert r.status_code == 200, r.text
    assert r.json()["resolution"] == "Both, by case (Which region?): North: Finance; South: Treasury"
    m = tenant.client.get(f"/maps/{mid}").json()
    assert m["version"] == v + 1 and m["errors"] == []
    model = ProcessModel.model_validate(m["model"])
    gate = next(n for n in model.nodes if n.name == "Which region?")
    assert sorted(f.condition or "" for f in model.flows if f.source_id == gate.id) == ["North", "South"]
    assert f"conflict_{owner['id']}" not in {q.id for q in model.open_questions}


def test_agenda_addresses_the_people_who_described_each_step(tenant: TenantCtx) -> None:
    merged_project(tenant)
    tenant.client.put(f"/projects/{tenant.project_id}/speakers/Sana", json={"role": "owner"})
    r = tenant.client.get(f"/projects/{tenant.project_id}/agenda")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert "attachment" in r.headers["content-disposition"]
    md = r.text
    assert md.startswith("# Next meeting: Invoices")
    assert "## For Marco and Sana (process owner)" in md
    assert "Who does 'Pay supplier in weekly payment run': Finance or Treasury?" in md
    assert "The process owner's account is Treasury." in md
    assert "_(D1)_" in md and "_(G1)_" in md
    assert "Or does it depend on the case" in md


POLICY_TEXT = (CASE / "policy.txt").read_bytes()


def policy_model() -> ProcessModel:
    """What the extraction reads from policy.txt: meeting one's process, but with a $10,000
    threshold and a VAT check the meetings never mentioned (also used by scripts/seed_demo.py)."""
    return ProcessModel.model_validate_json((CASE / "policy_model.json").read_text())


def test_policy_differences_are_listed_apart_and_can_be_settled(tenant: TenantCtx) -> None:
    ctx = merged_project(tenant)
    meeting_points = len(conflicts(tenant, origin="meeting"))
    up = tenant.client.post(
        f"/projects/{tenant.project_id}/transcripts", params={"purpose": "policy"},
        files={"file": ("invoice-policy.txt", POLICY_TEXT)},
    )  # fmt: skip
    assert up.status_code == 201 and up.json()["purpose"] == "policy", up.text
    v_before = version(tenant, ctx["merged_map_id"])
    job = tenant.process(up.json()["id"], FakeLLM(policy_model()))
    assert job["status"] == "done", job["error"]

    assert version(tenant, ctx["merged_map_id"]) == v_before  # a policy is never merged into the map
    assert len(conflicts(tenant, origin="meeting")) == meeting_points
    diffs = conflicts(tenant, origin="policy")
    kinds = sorted(c["kind"] for c in diffs)
    assert "missing_step" in kinds and "unofficial_step" in kinds, kinds
    vat = next(c for c in diffs if c["kind"] == "missing_step")
    assert "Check supplier VAT number" in vat["description"]
    assert vat["sides"][1]["quotes"] and vat["sides"][1]["quotes"][0]["policy"] is True
    bank = next(c for c in diffs if c["kind"] == "unofficial_step")
    assert "Validate supplier bank details" in bank["description"]
    project = tenant.client.get(f"/projects/{tenant.project_id}").json()
    assert project["open_policy_differences"] == len(diffs)
    assert project["open_conflicts"] == meeting_points

    # Note one as a deviation; it stays settled when the check reruns after the next meeting.
    r = tenant.client.post(f"/conflicts/{bank['id']}/resolve", json={"note": "deviation"})
    assert r.status_code == 200 and r.json()["resolution"] == "Noted as a deviation from the policy"
    assert tenant.client.post(f"/conflicts/{vat['id']}/resolve", json={"option": 0}).status_code == 422  # no options
    meeting_conflict = conflicts(tenant, origin="meeting")[0]
    assert (
        tenant.client.post(f"/conflicts/{meeting_conflict['id']}/resolve", json={"note": "dismissed"}).status_code
        == 400
    )

    again = tenant.upload("transcript_2.txt", (CASE / "transcript_2.txt").read_bytes()).json()["id"]
    tenant.process(again, FakeLLM(ProcessModel.model_validate_json((CASE / "model_2.json").read_text())))
    reopened = [c for c in conflicts(tenant, origin="policy", status="open") if c["kind"] == "unofficial_step"]
    assert not any("Validate supplier bank details" in c["description"] for c in reopened)


def test_signoff_links_show_only_their_part_and_record_decisions(tenant: TenantCtx) -> None:
    ctx = merged_project(tenant)
    lanes = {x["name"]: x["id"] for x in tenant.client.get(f"/maps/{ctx['merged_map_id']}").json()["model"]["lanes"]}
    r = tenant.client.post(
        f"/projects/{tenant.project_id}/signoffs", json={"name": "Sana", "lane_ids": [lanes["Treasury"]]}
    )
    assert r.status_code == 201, r.text
    token, sid = r.json()["token"], r.json()["id"]
    assert token.startswith("rv_") and r.json()["status"] == "pending"
    assert tenant.client.get(f"/projects/{tenant.project_id}/signoffs").json()[0]["token"] is None  # shown once
    bad = tenant.client.post(f"/projects/{tenant.project_id}/signoffs", json={"name": "X", "lane_ids": ["nope"]})
    assert bad.status_code == 400

    # The reviewer needs no API key: the link is the credential.
    from fastapi.testclient import TestClient

    from app.main import app

    anon = TestClient(app)
    review = anon.get(f"/review/{token}").json()
    assert review["process"] == "Invoices" and review["lanes"] == ["Treasury"]
    assert {s["lane"] for s in review["steps"]} == {"Treasury"}
    bank = next(s for s in review["steps"] if s["name"] == "Validate supplier bank details")
    assert bank["quotes"] and bank["goes_to"][0]["name"] == "Pay supplier in weekly payment run"
    assert anon.get("/review/rv_not-a-real-token").status_code == 404
    assert anon.get(f"/projects/{tenant.project_id}/signoffs").status_code == 401

    d = anon.post(f"/review/{token}", json={"decision": "changes_requested", "comment": "We pay on Thursdays."})
    assert d.status_code == 200 and d.json()["decision"] == "changes_requested"
    row = tenant.client.get(f"/projects/{tenant.project_id}/signoffs").json()[0]
    assert row["status"] == "changes_requested" and row["comment"] == "We pay on Thursdays."
    assert row["decided_version"] == row["current_version"]
    actions = [a["action"] for a in tenant.client.get("/audit").json()]
    assert "signoff" in actions and "request_signoff" in actions

    # Another organization can't see or revoke it; revoking ends the link.
    other = make_tenant()
    assert other.client.delete(f"/signoffs/{sid}").status_code == 404
    assert tenant.client.delete(f"/signoffs/{sid}").json()["status"] == "revoked"
    assert anon.get(f"/review/{token}").status_code == 410

    assert tenant.client.delete(f"/projects/{tenant.project_id}").json()["signoffs"] == 1


def test_inbox_lists_open_work_across_processes(tenant: TenantCtx) -> None:
    merged_project(tenant)
    items = tenant.client.get("/inbox").json()
    refs = [i["ref"] for i in items if i["kind"] == "disagreement"]
    assert refs == ["D1", "D2", "D3"]
    assert {i["kind"] for i in items} >= {"disagreement", "gap"}
    assert all(i["project_name"] == "Invoices" and i["tab"] for i in items)
    assert make_tenant().client.get("/inbox").json() == []  # another org sees none of it
