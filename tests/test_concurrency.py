"""Concurrent edits: version checks (If-Match / 412) and the row locks behind them."""

import threading
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app import maps
from app.api.maps import get_llm
from app.db.models import ProcessMap, Project, Transcript
from app.db.tenancy import tenant_session
from app.main import app
from app.models.process import ProcessModel
from app.pipeline.edit import EditPlan
from app.projects import merge_into_project
from tests.conftest import FakeLLM, TenantCtx, gold_model, needs_services
from tests.test_projects import merged_project
from tests.test_validate import ScriptedLLM

pytestmark = needs_services
CASE = Path(__file__).parent.parent / "eval" / "gold_merge" / "01_invoice_two_meetings"
EDITED = Path(__file__).parent / "fixtures" / "bpmnjs_edited_invoice.bpmn"


def _map(t: TenantCtx) -> tuple[str, Any]:
    tid = t.upload("t.vtt", (CASE / "transcript_1.vtt").read_bytes()).json()["id"]
    map_id = t.process(tid, FakeLLM(gold_model("01_invoice_approval")))["map_id"]
    return map_id, t.client.get(f"/maps/{map_id}")


def _put(t: TenantCtx, map_id: str, if_match: str | None) -> Any:
    headers = {"Content-Type": "application/xml", **({"If-Match": if_match} if if_match else {})}
    return t.client.put(f"/maps/{map_id}/bpmn", content=EDITED.read_bytes(), headers=headers)


def test_etag_and_stale_saves_are_refused(tenant: TenantCtx) -> None:
    map_id, r = _map(tenant)
    assert r.headers["etag"] == '"1"'

    ok = _put(tenant, map_id, '"1"')
    assert ok.status_code == 200 and ok.headers["etag"] == '"2"' and ok.json()["version"] == 2

    stale = _put(tenant, map_id, '"1"')  # someone still holding v1
    assert stale.status_code == 412 and stale.headers["etag"] == '"2"'
    assert "changed by someone else" in stale.json()["detail"]
    assert tenant.client.get(f"/maps/{map_id}").json()["version"] == 2  # nothing written

    assert _put(tenant, map_id, None).status_code == 200  # no If-Match: applies to current (v3)
    assert _put(tenant, map_id, 'W/"3"').status_code == 200  # weak ETag syntax accepted
    assert _put(tenant, map_id, "banana").status_code == 400

    assert tenant.client.post(f"/maps/{map_id}/undo", headers={"If-Match": '"2"'}).status_code == 412
    assert tenant.client.post(f"/maps/{map_id}/undo", headers={"If-Match": '"4"'}).json()["version"] == 3


def test_chat_checks_before_and_after_the_llm(tenant: TenantCtx) -> None:
    map_id, _ = _map(tenant)
    plan = EditPlan.model_validate({"reply": "ok", "ops": [{"op": "rename_node", "node_id": "t_pay", "name": "Pay"}]})

    llm = ScriptedLLM(plan)
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        r = tenant.client.post(f"/maps/{map_id}/chat", json={"instruction": "x"}, headers={"If-Match": '"7"'})
        assert r.status_code == 412 and llm.calls == []  # refused before spending an LLM call

        class EditedMeanwhile(ScriptedLLM):
            """While the LLM 'thinks', someone saves a visual edit."""

            def structured(self, *a: Any, **k: Any) -> Any:
                assert _put(tenant, map_id, '"1"').status_code == 200
                return super().structured(*a, **k)

        app.dependency_overrides[get_llm] = lambda: EditedMeanwhile(plan)
        r = tenant.client.post(f"/maps/{map_id}/chat", json={"instruction": "x"}, headers={"If-Match": '"1"'})
        assert r.status_code == 412  # ops were planned on v1; v2 exists now
        m = tenant.client.get(f"/maps/{map_id}").json()
        assert m["version"] == 2 and "Pay" not in [n["name"] for n in m["model"]["nodes"]]
    finally:
        app.dependency_overrides.clear()


def test_resolving_a_conflict_checks_the_map_version(tenant: TenantCtx) -> None:
    ctx = merged_project(tenant)
    conflict = tenant.client.get(f"/projects/{tenant.project_id}/conflicts").json()[0]
    r = tenant.client.post(f"/conflicts/{conflict['id']}/resolve", json={"option": None}, headers={"If-Match": '"1"'})
    assert r.status_code == 412
    version = tenant.client.get(f"/maps/{ctx['merged_map_id']}").json()["version"]
    ok = tenant.client.post(
        f"/conflicts/{conflict['id']}/resolve", json={"option": None}, headers={"If-Match": f'"{version}"'}
    )
    assert ok.status_code == 200


def test_simultaneous_saves_one_wins(tenant: TenantCtx) -> None:
    """Two writers start from v1 at the same instant: the row lock lets exactly one through."""
    map_id, _ = _map(tenant)
    model = gold_model("01_invoice_approval")
    start = threading.Barrier(2)
    outcomes: list[str] = []

    def writer(name: str) -> None:
        with tenant_session(tenant.org_id) as db:
            start.wait()
            pmap = maps.lock_map(db, map_id)
            assert pmap is not None
            try:
                maps.check_version(pmap, 1)
            except maps.StaleVersion:
                outcomes.append("stale")
                return
            renamed = model.model_copy(update={"name": name})
            maps.commit_version(db, pmap, renamed, "visual", maps.current_positions(pmap))
            db.commit()
            outcomes.append("saved")

    threads = [threading.Thread(target=writer, args=(f"writer {i}",)) for i in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    assert sorted(outcomes) == ["saved", "stale"]
    assert tenant.client.get(f"/maps/{map_id}").json()["version"] == 2


def test_meetings_finishing_together_make_one_merged_map(tenant: TenantCtx) -> None:
    """Two transcripts of a brand-new project merge at once: one seeds the map, the other
    waits for the project lock and merges into it (no second merged map)."""
    tids = [tenant.upload(f"t{k}.txt", (CASE / "transcript_2.txt").read_bytes()).json()["id"] for k in (1, 2)]
    models = [ProcessModel.model_validate_json((CASE / f"model_{k}.json").read_text()) for k in (1, 2)]
    start = threading.Barrier(2)
    errors: list[BaseException] = []

    def merge(tid: str, model: ProcessModel) -> None:
        try:
            with tenant_session(tenant.org_id) as db:
                project = db.get_one(Project, tenant.project_id)  # both see "no merged map yet"
                transcript = db.get_one(Transcript, tid)
                start.wait()
                merge_into_project(db, project, transcript, model, FakeLLM(model))
                db.commit()
        except BaseException as e:  # surfaced below
            errors.append(e)

    threads = [threading.Thread(target=merge, args=a) for a in zip(tids, models, strict=True)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert errors == []
    with tenant_session(tenant.org_id) as db:
        merged = db.scalar(
            select(func.count(ProcessMap.id)).where(
                ProcessMap.project_id == tenant.project_id, ProcessMap.transcript_id.is_(None)
            )
        )
        project = db.get_one(Project, tenant.project_id)
        versions = db.get_one(ProcessMap, project.merged_map_id).current_version
    assert merged == 1 and versions == 2  # seeded once, then the second meeting merged on top
