"""Multi-meeting projects through the API: merge, conflicts, deletion, retention, audit."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app import storage
from app.db.models import AuditLog, Conflict, Job, MapVersion, ProcessMap, Project, Transcript
from app.db.tenancy import system_session
from app.models.process import TASK_TYPES, ProcessModel
from app.pipeline.convert import validate_xsd
from app.projects import purge_expired
from tests.conftest import FakeLLM, TenantCtx, make_tenant, needs_services

pytestmark = needs_services
CASE = Path(__file__).parent.parent / "eval" / "gold_merge" / "01_invoice_two_meetings"


def merged_project(t: TenantCtx) -> dict[str, Any]:
    """Upload + process both invoice meetings into t's project; returns ids for later checks."""
    ids = []
    for k, name in ((1, "transcript_1.vtt"), (2, "transcript_2.txt")):
        tid = t.upload(name, (CASE / name).read_bytes()).json()["id"]
        model = ProcessModel.model_validate_json((CASE / f"model_{k}.json").read_text())
        job = t.process(tid, FakeLLM(model))
        assert job["status"] == "done", job["error"]
        ids.append(tid)
    project = t.client.get(f"/projects/{t.project_id}").json()
    return {"transcripts": ids, "merged_map_id": project["merged_map_id"], "project": project}


def test_two_meetings_merge_without_duplicates_and_surface_conflicts(tenant: TenantCtx) -> None:
    ctx = merged_project(tenant)
    m = tenant.client.get(f"/maps/{ctx['merged_map_id']}").json()
    validate_xsd(m["bpmn_xml"].encode())
    model = ProcessModel.model_validate(m["model"])

    tasks = [n.name for n in model.nodes if n.type in TASK_TYPES]
    assert len(tasks) == len(set(tasks)) == 7  # 6 shared steps once each + the new Treasury check
    assert "Validate supplier bank details" in tasks
    assert m["version"] == 2 and m["errors"] == []

    # Matched steps carry evidence from both meetings.
    t1, t2 = ctx["transcripts"]
    pay = next(n for n in model.nodes if n.id == "t_pay")
    assert {c.split(":")[0] for c in pay.source_segment_ids} == {t1, t2}
    assert {s["segment_id"].split(":")[0] for s in m["segments"]} == {t1, t2}

    conflicts = tenant.client.get(f"/projects/{tenant.project_id}/conflicts").json()
    assert sorted(c["kind"] for c in conflicts) == ["condition", "condition", "owner"]
    owner = next(c for c in conflicts if c["kind"] == "owner")
    assert owner["options"] == ["Finance", "Treasury"] and owner["node_ids"] == ["t_pay"]
    assert {q.id for q in model.open_questions} >= {f"conflict_{c['id']}" for c in conflicts}
    assert ctx["project"]["open_conflicts"] == 3

    # Resolving drops the open question in a new map version.
    r = tenant.client.post(f"/conflicts/{owner['id']}/resolve")
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    after = tenant.client.get(f"/maps/{ctx['merged_map_id']}").json()
    assert after["version"] == 3
    assert f"conflict_{owner['id']}" not in {q["id"] for q in after["model"]["open_questions"]}
    assert len(tenant.client.get(f"/projects/{tenant.project_id}/conflicts?status=open").json()) == 2


def test_merge_keeps_user_edits(tenant: TenantCtx) -> None:
    tid = tenant.upload("transcript_1.vtt", (CASE / "transcript_1.vtt").read_bytes()).json()["id"]
    tenant.process(tid, FakeLLM(ProcessModel.model_validate_json((CASE / "model_1.json").read_text())))
    merged_id = tenant.client.get(f"/projects/{tenant.project_id}").json()["merged_map_id"]

    from app.api.maps import get_llm
    from app.main import app
    from app.pipeline.edit import EditPlan
    from tests.test_validate import ScriptedLLM

    plan = EditPlan.model_validate(
        {"reply": "", "ops": [{"op": "rename_node", "node_id": "t_enter", "name": "Book invoice in SAP"}]}
    )
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(plan)
    try:
        assert tenant.client.post(f"/maps/{merged_id}/chat", json={"instruction": "it's SAP"}).status_code == 200
    finally:
        app.dependency_overrides.clear()

    tid2 = tenant.upload("transcript_2.txt", (CASE / "transcript_2.txt").read_bytes()).json()["id"]
    tenant.process(tid2, FakeLLM(ProcessModel.model_validate_json((CASE / "model_2.json").read_text())))
    m = tenant.client.get(f"/maps/{merged_id}").json()
    names = [n["name"] for n in m["model"]["nodes"]]
    assert "Book invoice in SAP" in names and "Enter invoice into ERP" not in names  # user's rename survived
    history = tenant.client.get(f"/maps/{merged_id}/versions").json()
    assert [h["source"] for h in history] == ["merge", "chat", "merge"]


def _rows(project_id: str, map_id: str) -> dict[str, int]:
    with system_session() as db:

        def count(q: Any) -> int:
            return int(db.scalar(select(func.count()).select_from(q.subquery())) or 0)

        return {
            "projects": count(select(Project.id).where(Project.id == project_id)),
            "transcripts": count(select(Transcript.id).where(Transcript.project_id == project_id)),
            "maps": count(select(ProcessMap.id).where(ProcessMap.project_id == project_id)),
            "map_versions": count(select(MapVersion.id).where(MapVersion.map_id == map_id)),
            "conflicts": count(select(Conflict.id).where(Conflict.project_id == project_id)),
            "jobs": count(
                select(Job.id)
                .join(Transcript, Job.transcript_id == Transcript.id, isouter=True)
                .where(Job.transcript_id.is_(None) | (Transcript.project_id == project_id))
            ),
        }


def test_delete_project_leaves_nothing_behind(tenant: TenantCtx) -> None:
    ctx = merged_project(tenant)
    prefix = storage.project_prefix(tenant.org_id, tenant.project_id)
    assert len(storage.list_keys(prefix)) == 2
    assert all(v > 0 for k, v in _rows(tenant.project_id, ctx["merged_map_id"]).items() if k != "jobs")

    r = tenant.client.delete(f"/projects/{tenant.project_id}")
    assert r.status_code == 200, r.text
    assert r.json()["objects"] == 2 and r.json()["transcripts"] == 2

    assert set(_rows(tenant.project_id, ctx["merged_map_id"]).values()) == {0}
    assert storage.list_keys(prefix) == []
    with system_session() as db:
        transcript_jobs = db.scalar(select(func.count(Job.id)).where(Job.transcript_id.in_(ctx["transcripts"])))
    assert transcript_jobs == 0
    assert tenant.client.get(f"/projects/{tenant.project_id}").status_code == 404
    assert tenant.client.get(f"/maps/{ctx['merged_map_id']}").status_code == 404

    # Only metadata-only audit entries remain (by design), including the deletion itself.
    audit = tenant.client.get("/audit").json()
    assert audit[0]["action"] == "delete" and audit[0]["target_id"] == tenant.project_id


def test_retention_purges_raw_files_and_text_but_keeps_maps() -> None:
    t = make_tenant(retention_days=30)
    tid = t.upload("transcript_1.vtt", (CASE / "transcript_1.vtt").read_bytes()).json()["id"]
    job = t.process(tid, FakeLLM(ProcessModel.model_validate_json((CASE / "model_1.json").read_text())))
    keep = make_tenant()  # no retention: must be untouched
    keep_tid = keep.upload("transcript_1.vtt", (CASE / "transcript_1.vtt").read_bytes()).json()["id"]
    keep.process(keep_tid, FakeLLM(ProcessModel.model_validate_json((CASE / "model_1.json").read_text())))

    assert purge_expired(now=datetime.now(UTC) + timedelta(days=29)) == 0
    assert purge_expired(now=datetime.now(UTC) + timedelta(days=31)) >= 1

    with system_session() as db:
        purged, kept = db.get_one(Transcript, tid), db.get_one(Transcript, keep_tid)
        assert purged.segments is None and purged.content_expired_at is not None
        assert kept.segments and kept.content_expired_at is None
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(AuditLog.action == "retention_purge", AuditLog.target_id == tid)
            )
            == 1
        )
    assert storage.list_keys(storage.project_prefix(t.org_id, t.project_id)) == []

    m = t.client.get(f"/maps/{job['map_id']}")
    assert m.status_code == 200 and m.json()["segments"] == []  # map intact, quotes gone
    assert t.client.get(f"/projects/{t.project_id}").json()["transcripts"][0]["content_expired"] is True
    assert t.client.post(f"/transcripts/{tid}/process").status_code == 410


def test_audit_log_records_actions_without_content(tenant: TenantCtx) -> None:
    merged_project(tenant)
    audit = tenant.client.get("/audit?limit=50").json()
    actions = {a["action"] for a in audit}
    assert {"create", "upload", "process", "merge"} <= actions
    assert all(a["api_key_id"] for a in audit if a["action"] in ("create", "upload", "process"))
    blob = str(audit).lower()
    assert "treasury validates" not in blob and "supplier invoice lands" not in blob  # never meeting text


def test_exports(tenant: TenantCtx, monkeypatch: Any) -> None:
    import shutil

    from app.core.config import get_settings

    ctx = merged_project(tenant)
    mid = ctx["merged_map_id"]

    bpmn = tenant.client.get(f"/maps/{mid}/export/bpmn")
    assert (
        bpmn.status_code == 200 and 'filename="Supplier_invoice_approval.bpmn"' in bpmn.headers["content-disposition"]
    )
    validate_xsd(bpmn.content)

    md = tenant.client.get(f"/maps/{mid}/export/md").text
    assert md.startswith("# Supplier invoice approval")
    assert "**Validate supplier bank details** — Treasury" in md
    assert "transcript_2.txt" in md and "treasury validates the supplier" in md.lower()  # cited quote + source
    assert "## Open questions" in md and "Meetings disagree (owner)" in md
    assert tenant.client.get(f"/maps/{mid}/export/pdf").status_code == 422

    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(chrome).exists():
        monkeypatch.setattr(get_settings(), "export_browser_channel", "chrome")
    elif shutil.which("chromium") is None:
        return  # no browser here; `playwright install chromium` to run the image checks
    svg = tenant.client.get(f"/maps/{mid}/export/svg")
    assert svg.status_code == 200, svg.text
    assert (
        svg.content.startswith(b"<?xml") and b"Validate" in svg.content and b"Treasury" in svg.content
    )  # labels wrap into tspans
    png = tenant.client.get(f"/maps/{mid}/export/png")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n" and len(png.content) > 20_000
    Path(__file__).parent.joinpath(".export_check.png").write_bytes(png.content)  # for a manual look; gitignored
    assert {a["details"]["format"] for a in tenant.client.get("/audit").json() if a["action"] == "export"} == {
        "bpmn",
        "md",
        "svg",
        "png",
    }
