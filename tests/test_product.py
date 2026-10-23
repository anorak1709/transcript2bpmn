"""Review queue, corrections flywheel, improvements, sign-up, demo sandboxes, live interviews,
element evidence and the Camunda push: through the API, with the stand-in AI (no credits)."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.models.process import ProcessModel
from app.models.transcript import Segment
from app.pipeline.edit import EditPlan
from app.pipeline.transcribe.base import Transcriber, Transcription
from tests.conftest import FakeLLM, TenantCtx, make_tenant, needs_services
from tests.test_projects import CASE, merged_project
from tests.test_validate import ScriptedLLM

pytestmark = needs_services


def test_review_queue_puts_uncited_and_unsure_steps_first(tenant: TenantCtx) -> None:
    ctx = merged_project(tenant)
    mid = ctx["merged_map_id"]
    q = tenant.client.get(f"/maps/{mid}/review").json()
    assert q and all(not i["reviewed"] for i in q)
    flagged = [i for i in q if i["reason"]]
    assert q[: len(flagged)] == flagged  # flagged steps lead
    confs = [i["confidence"] for i in q[len(flagged) :]]
    assert confs == sorted(confs)
    first = q[0]["node_id"]
    assert tenant.client.post(f"/maps/{mid}/review/{first}").json() == {"checked": True}
    again = tenant.client.get(f"/maps/{mid}/review").json()
    assert again[-1]["node_id"] == first and again[-1]["reviewed"]  # checked steps drop to the end
    assert tenant.client.post(f"/maps/{mid}/review/nope").status_code == 404
    assert tenant.client.get(f"/maps/{mid}").json()["version"] == 2  # checking isn't an edit


def _chat(tenant: TenantCtx, mid: str, plan: EditPlan) -> Any:
    from app.api.maps import get_llm

    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(plan)
    try:
        return tenant.client.post(f"/maps/{mid}/chat", json={"instruction": "fix it"})
    finally:
        app.dependency_overrides.pop(get_llm, None)


def test_corrections_are_recorded_and_exported_only_with_consent(tenant: TenantCtx) -> None:
    from app.corrections import export_cases
    from app.db.models import Organization
    from app.db.tenancy import tenant_session
    from eval.corrections_eval import learned

    ctx = merged_project(tenant)
    mid = ctx["merged_map_id"]
    lanes = {x["name"]: x["id"] for x in tenant.client.get(f"/maps/{mid}").json()["model"]["lanes"]}
    plan = EditPlan.model_validate(
        {
            "reply": "Done.",
            "ops": [
                {"op": "rename_node", "node_id": "t_pay", "name": "Release supplier payment"},
                {"op": "reassign_lane", "node_id": "t_pay", "lane_id": lanes["Treasury"]},
                {"op": "remove_node", "node_id": "t_return", "reconnect": True},
            ],
        }
    )
    assert _chat(tenant, mid, plan).status_code == 200
    got = tenant.client.get("/corrections").json()
    assert got["by_kind"]["rename"] == 1 and got["by_kind"]["move"] == 1 and got["by_kind"]["delete"] == 1
    rename = next(c for c in got["recent"] if c["kind"] == "rename")
    assert rename["before"] == {"name": "Pay supplier in weekly payment run"} and rename["via"] == "chat"

    with tenant_session(tenant.org_id) as db:
        org = db.get_one(Organization, tenant.org_id)
        assert export_cases(db, org) == []  # off by default: nothing leaves the workspace
    assert tenant.client.put("/workspace", json={"share_corrections": "anonymised"}).status_code == 200
    with tenant_session(tenant.org_id) as db:
        (case,) = export_cases(db, db.get_one(Organization, tenant.org_id))
        assert case["meetings"] is None and case["process"] is None  # no meeting text, no names
        assert {c["kind"] for c in case["corrections"]} >= {"rename", "move", "delete"}
    tenant.client.put("/workspace", json={"share_corrections": "full"})
    with tenant_session(tenant.org_id) as db:
        (case,) = export_cases(db, db.get_one(Organization, tenant.org_id))
        assert len(case["meetings"]) == 2 and any("treasury" in x["text"].lower() for x in case["meetings"][1])

    # The eval check: the corrected map "learned" every fix; the AI's original draft didn't.
    corrected = ProcessModel.model_validate(tenant.client.get(f"/maps/{mid}").json()["model"])
    original = ProcessModel.model_validate(_version(tenant, mid, 2))  # the AI's merged draft
    for fix in case["corrections"]:
        if fix["kind"] in ("rename", "move", "delete"):
            assert learned(fix, corrected) and not learned(fix, original), fix


def _version(tenant: TenantCtx, mid: str, v: int) -> dict[str, Any]:
    from app.db.models import MapVersion
    from app.db.tenancy import tenant_session

    with tenant_session(tenant.org_id) as db:
        from sqlalchemy import select

        return dict(db.scalars(select(MapVersion).where(MapVersion.map_id == mid, MapVersion.version == v)).one().model)


def test_improvements_from_rules_and_ai_only_on_request(tenant: TenantCtx) -> None:
    ctx = merged_project(tenant)
    mid = ctx["merged_map_id"]
    ideas = tenant.client.get(f"/maps/{mid}/improvements").json()
    kinds = {i["kind"] for i in ideas}
    assert "automate" in kinds and "handoff" in kinds
    assert any("Enter invoice into ERP" in i["title"] for i in ideas)

    from app.api.maps import get_llm
    from app.pipeline.improve import _Ideas

    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(
        _Ideas.model_validate(
            {
                "ideas": [
                    {
                        "title": "Pay daily",
                        "detail": "Weekly runs delay payment.",
                        "step_names": ["Pay supplier in weekly payment run"],
                    }
                ]
            }
        )  # fmt: skip
    )
    try:
        r = tenant.client.post(f"/maps/{mid}/improvements/ai")
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 200 and r.json()[0]["node_ids"] == ["t_pay"] and r.json()[0]["kind"] == "ai"


def _capture_emails(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []
    monkeypatch.setattr("app.api.auth.send", lambda to, subject, text, html: sent.append({"to": to, "text": text}))
    return sent


def _link_token(mail: dict[str, str]) -> str:
    m = re.search(r"token=(ml_[\w-]+)", mail["text"])
    assert m, mail
    return m.group(1)


def test_sign_up_by_magic_link_and_invite_a_colleague(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _capture_emails(monkeypatch)
    anon = TestClient(app)
    email = f"ana.{datetime.now().timestamp()}@example.com"
    assert anon.post("/auth/magic-link", json={"email": "not-an-email"}).status_code == 422
    assert anon.post("/auth/magic-link", json={"email": email.upper()}).status_code == 202
    assert sent[-1]["to"] == email and "/app/auth?token=ml_" in sent[-1]["text"]
    token = _link_token(sent[-1])

    s = anon.post("/auth/verify", json={"token": token}).json()
    assert s["email"] == email and s["workspace_name"].startswith("ana.")
    assert anon.post("/auth/verify", json={"token": token}).status_code == 401  # one use only
    ana = TestClient(app, headers={"Authorization": f"Bearer {s['key']}"})
    me = ana.get("/auth/me").json()
    assert me["email"] == email and me["workspace"]["role"] == "owner" and not me["sandbox"]
    assert ana.post("/projects", json={"name": "Hiring"}).status_code == 201  # a real, usable workspace

    # Invite a colleague: their link signs them into Ana's workspace.
    colleague = f"bo.{datetime.now().timestamp()}@example.com"
    inv = ana.post("/invites", json={"email": colleague})
    assert inv.status_code == 201 and sent[-1]["to"] == colleague and "invited" in sent[-1]["text"]
    bo = anon.post("/auth/verify", json={"token": _link_token(sent[-1])}).json()
    assert bo["workspace_id"] == s["workspace_id"]
    bo_client = TestClient(app, headers={"Authorization": f"Bearer {bo['key']}"})
    assert [p["name"] for p in bo_client.get("/projects").json()] == ["Hiring"]
    assert {m["email"] for m in ana.get("/members").json()} == {email, colleague}
    assert ana.get("/invites").json() == []  # accepted

    # Signing in again lands in their workspace; signing out ends the session.
    anon.post("/auth/magic-link", json={"email": email})
    again = anon.post("/auth/verify", json={"token": _link_token(sent[-1])}).json()
    assert again["workspace_id"] == s["workspace_id"]
    assert ana.post("/auth/logout").status_code == 200
    assert ana.get("/auth/me").status_code == 401

    # An expired link is refused.
    from app.db.models import LoginToken
    from app.db.tenancy import system_session

    anon.post("/auth/magic-link", json={"email": email})
    stale = _link_token(sent[-1])
    with system_session() as db:
        import hashlib

        row = db.query(LoginToken).filter_by(token_hash=hashlib.sha256(stale.encode()).hexdigest()).one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    assert anon.post("/auth/verify", json={"token": stale}).status_code == 401


def test_demo_sandbox_is_instant_ai_free_and_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.models import Organization
    from app.db.tenancy import system_session
    from app.demo import purge_sandboxes

    anon = TestClient(app)
    monkeypatch.setattr(get_settings(), "demo_sandboxes", False)
    assert anon.post("/demo/sandbox").status_code == 404
    monkeypatch.setattr(get_settings(), "demo_sandboxes", True)
    assert anon.get("/demo/status").json()["sandboxes"] is True
    r = anon.post("/demo/sandbox")
    assert r.status_code == 201, r.text
    org_id = r.json()["workspace_id"]
    v = TestClient(app, headers={"Authorization": f"Bearer {r.json()['key']}"})
    projects = v.get("/projects").json()
    assert sorted(p["name"] for p in projects) == ["New employee onboarding", "Supplier invoice approval"]
    invoice = next(p for p in projects if p["name"] == "Supplier invoice approval")
    assert invoice["open_conflicts"] == 3 and invoice["open_policy_differences"] > 0
    assert v.get("/auth/me").json()["sandbox"] is True
    assert v.get("/integrations").json()["ai"] is False

    # Nothing in a sandbox reaches an AI provider.
    up = v.post(f"/projects/{invoice['id']}/transcripts", files={"file": ("t.txt", b"Ann: hi")})
    assert up.status_code == 403 and "demo" in up.json()["detail"]
    assert v.post(f"/transcripts/{invoice['transcripts'][0]['id']}/process").status_code == 403
    assert v.post(f"/maps/{invoice['merged_map_id']}/chat", json={"instruction": "x"}).status_code == 403
    assert v.post(f"/projects/{invoice['id']}/live").status_code == 403
    assert v.get(f"/maps/{invoice['merged_map_id']}/export/md").status_code == 200  # the rest works

    assert purge_sandboxes(now=datetime.now(UTC) + timedelta(hours=25)) >= 1
    with system_session() as db:
        assert db.get(Organization, org_id) is None
    assert v.get("/projects").status_code == 401


class _FakeTranscriber(Transcriber):
    def __init__(self, lines: list[tuple[str, str, float]]) -> None:
        self.lines = lines

    def transcribe(self, audio_path: Path) -> Transcription:
        return Transcription(
            segments=[
                Segment(segment_id=f"r{i}", speaker=who, start_ts=t, end_ts=t + 4, text=text)
                for i, (who, text, t) in enumerate(self.lines, 1)
            ],
            diarization_available=True,
        )


def test_live_interview_grows_a_draft_then_merges(tenant: TenantCtx) -> None:
    from app.live import process_chunk
    from app.workers.jobs import run_job

    model = ProcessModel.model_validate_json((CASE / "model_1.json").read_text())
    live = tenant.client.post(f"/projects/{tenant.project_id}/live").json()
    tid = live["transcript_id"]
    assert live["status"] == "recording" and live["lines"] == [] and live["chunk_seconds"] > 0

    first = _FakeTranscriber([("Priya", "A supplier invoice lands in the AP inbox and we enter it into the ERP.", 2.0)])
    r = tenant.client.post(f"/transcripts/{tid}/live/chunks?index=0&offset=0", files={"file": ("c0.webm", b"webm")})
    assert r.status_code == 202 and tenant.queue.jobs[-1][0] == "live_chunk"
    assert process_chunk(tid, 0, 0.0, FakeLLM(model), first) == 1
    after1 = tenant.client.get(f"/transcripts/{tid}/live").json()
    assert after1["map_id"] and after1["map_version"] == 1 and after1["lines"][0]["segment_id"] == "s1"

    second = _FakeTranscriber([("Marco", "Anything over five thousand dollars comes to me in finance.", 5.0)])
    tenant.client.post(f"/transcripts/{tid}/live/chunks?index=1&offset=180", files={"file": ("c1.webm", b"webm")})
    process_chunk(tid, 1, 180.0, FakeLLM(model), second)
    after2 = tenant.client.get(f"/transcripts/{tid}/live").json()
    assert [x["segment_id"] for x in after2["lines"]] == ["s1", "s2"]
    assert after2["lines"][1]["start_ts"] == 185.0  # shifted onto the interview's timeline
    assert after2["map_id"] == after1["map_id"] and after2["map_version"] == 2  # the same draft, redrawn

    job = tenant.client.post(f"/transcripts/{tid}/live/finish").json()
    assert (
        tenant.client.post(
            f"/transcripts/{tid}/live/chunks?index=2&offset=360", files={"file": ("c.webm", b"x")}
        ).status_code
        == 409
    )
    run_job(job["id"], FakeLLM(model))
    done = tenant.client.get(f"/jobs/{job['id']}").json()
    assert done["status"] == "done", done["error"]
    assert done["map_id"] == after1["map_id"]  # the draft map becomes the meeting's map
    assert tenant.client.get(f"/projects/{tenant.project_id}").json()["merged_map_id"]  # merged like any meeting


def test_element_evidence_counts_waits_and_subprocesses(tenant: TenantCtx) -> None:
    text = b"Ann: We wait three days for the supplier.\nBo: Vendor setup is a separate process.\nAnn: Then we pay.\n"
    tid = tenant.upload("waits.txt", text).json()["id"]
    tenant.process(tid, FakeLLM(ProcessModel.model_validate_json((CASE / "model_1.json").read_text())))
    ev = tenant.client.get("/insights/bpmn-elements").json()
    assert ev["meetings"] == 1 and ev["with_timers"] == 1 and ev["with_subprocesses"] == 1
    assert "three days" in ev["timer_examples"][0]


def test_send_to_camunda(tenant: TenantCtx, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = merged_project(tenant)
    mid = ctx["merged_map_id"]
    assert tenant.client.get("/integrations").json()["camunda"] is False
    assert tenant.client.post(f"/maps/{mid}/push/camunda").status_code == 501
    for k, v in {"camunda_client_id": "cid", "camunda_client_secret": "sec", "camunda_project_id": "p1"}.items():
        monkeypatch.setattr(get_settings(), k, v)
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if "oauth" in str(req.url):
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(201, json={"id": "file-123"})

    real = httpx.Client
    monkeypatch.setattr(
        "app.integrations.camunda.httpx.Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    r = tenant.client.post(f"/maps/{mid}/push/camunda")
    assert r.status_code == 200, r.text
    assert r.json()["url"].endswith("/diagrams/file-123")
    token_req, file_req = calls
    assert b"client_credentials" in token_req.content and file_req.headers["authorization"] == "Bearer tok"
    body = __import__("json").loads(file_req.content)
    assert body["projectId"] == "p1" and body["fileType"] == "bpmn" and body["content"].startswith("<?xml")


def test_other_org_cannot_touch_this_workspace(tenant: TenantCtx) -> None:
    merged_project(tenant)
    other = make_tenant()
    assert other.client.get("/corrections").json()["total"] == 0
    assert other.client.get("/members").json() == []


def test_global_cap_ignores_spoofed_ips() -> None:
    """per_ip=False counts every caller together, so rotating X-Forwarded-For can't get around it."""
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.ratelimit import ip_limit

    class Counter:
        def __init__(self) -> None:
            self.n: dict[str, int] = {}

        async def incr(self, key: str) -> int:
            self.n[key] = self.n.get(key, 0) + 1
            return self.n[key]

        async def expire(self, key: str, s: int) -> None:
            pass

    app = SimpleNamespace(state=SimpleNamespace(redis=Counter()))
    check = ip_limit("t-all", 2, per_ip=False)
    reqs = [SimpleNamespace(app=app, headers={"fly-client-ip": f"10.0.0.{i}"}, client=None) for i in range(3)]
    asyncio.run(check(reqs[0]))  # type: ignore[arg-type]
    asyncio.run(check(reqs[1]))  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as e:
        asyncio.run(check(reqs[2]))  # type: ignore[arg-type]
    assert e.value.status_code == 429
