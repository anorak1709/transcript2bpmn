"""Cross-organization access must be impossible.

Two layers are tested: the HTTP surface (every route, discovered from the app, so a new
endpoint is covered automatically) and the session layer underneath it.
"""

import re
from typing import Any

import pytest
from sqlalchemy import select, update

from app.auth import create_key, verify
from app.db.base import SessionLocal
from app.db.models import ApiKey, Conflict, ProcessMap, Transcript
from app.db.tenancy import TenancyError, system_session, tenant_session
from app.main import app
from tests.conftest import TenantCtx, needs_services
from tests.test_projects import merged_project

pytestmark = needs_services
PUBLIC = {
    "/health",
    "/editor/{map_id}",
    "/viewer/{map_id}",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


def _routes() -> list[tuple[str, str]]:
    """Every API operation, from the OpenAPI schema (FastAPI resolves included routers there)."""
    return [
        (method.upper(), path) for path, ops in app.openapi()["paths"].items() if path not in PUBLIC for method in ops
    ]


@pytest.fixture
def victim(tenant: TenantCtx) -> dict[str, str]:
    """Org A with one of everything: project, transcripts, job, maps, conflicts."""
    ctx = merged_project(tenant)
    with tenant_session(tenant.org_id) as db:
        conflict = db.scalars(select(Conflict)).first()
        tmap = db.scalars(select(ProcessMap).where(ProcessMap.transcript_id.is_not(None))).first()
        assert conflict and tmap
        job = tenant.client.post(f"/transcripts/{ctx['transcripts'][0]}/process").json()
    return {
        "project_id": tenant.project_id,
        "transcript_id": ctx["transcripts"][0],
        "map_id": ctx["merged_map_id"],
        "transcript_map_id": tmap.id,
        "job_id": job["id"],
        "conflict_id": conflict.id,
        "org_id": tenant.org_id,
        "fmt": "md",  # exports: another org must not get an SOP (or any format) of this map
    }


def _call(client: Any, method: str, path: str) -> Any:
    kw: dict[str, Any] = {}
    if path.endswith("/chat"):
        kw["json"] = {"instruction": "rename everything"}
    elif path.endswith("/bpmn"):
        kw["content"], kw["headers"] = b"<x/>", {"Content-Type": "application/xml"}
    elif path.endswith("/transcripts") and method == "POST":
        kw["files"] = {"file": ("t.txt", b"Ann: hi")}
    elif path == "/projects" and method == "POST":
        kw["json"] = {"name": "x"}
    return client.request(method, path, **kw)


def test_every_route_requires_a_valid_key(tenant: TenantCtx) -> None:
    from fastapi.testclient import TestClient

    anon = TestClient(app)
    bad = TestClient(app, headers={"Authorization": "Bearer t2b_deadbeef_nope"})
    for method, path in _routes():
        concrete = re.sub(r"\{[^}]+\}", "x", path)
        for client in (anon, bad):
            assert _call(client, method, concrete).status_code == 401, f"{method} {path} without a valid key"


def test_revoked_key_stops_working(tenant: TenantCtx) -> None:
    assert verify(tenant.key) is not None
    with system_session() as db:
        db.execute(update(ApiKey).where(ApiKey.organization_id == tenant.org_id).values(revoked_at="2026-01-01"))
        db.commit()
    assert verify(tenant.key) is None
    assert tenant.client.get("/projects").status_code == 401


def test_no_route_reaches_another_orgs_data(victim: dict[str, str], other_tenant: TenantCtx) -> None:
    checked = 0
    for method, path in _routes():
        params = re.findall(r"\{([^}]+)\}", path)
        if not params:
            continue
        unknown = [p for p in params if p not in victim]
        assert not unknown, f"{method} {path}: add {unknown} to the victim fixture so this route is covered"
        concrete = path
        for p in params:
            concrete = concrete.replace("{" + p + "}", victim[p])
        r = _call(other_tenant.client, method, concrete)
        # 404, never 403: another org's ids must be indistinguishable from ids that don't exist.
        assert r.status_code == 404, f"{method} {concrete} -> {r.status_code} {r.text[:200]}"
        checked += 1
    assert checked == sum("{" in path for _, path in _routes()) >= 12  # every id-taking route was tried

    # Collection routes: B sees none of A's things.
    assert other_tenant.client.get("/projects").json() == [
        p for p in other_tenant.client.get("/projects").json() if p["id"] != victim["project_id"]
    ]
    assert victim["project_id"] not in {p["id"] for p in other_tenant.client.get("/projects").json()}
    assert all(a["target_id"] != victim["project_id"] for a in other_tenant.client.get("/audit").json())

    # And A's data is untouched by all of B's attempts (incl. DELETE / chat / undo / resolve).
    with tenant_session(victim["org_id"]) as db:
        assert db.get(ProcessMap, victim["map_id"]) is not None
        assert db.get_one(Conflict, victim["conflict_id"]).status == "open"


def test_session_layer_isolates_and_fails_closed(victim: dict[str, str], other_tenant: TenantCtx) -> None:
    with tenant_session(other_tenant.org_id) as db:
        assert db.get(Transcript, victim["transcript_id"]) is None
        assert db.scalars(select(Transcript).where(Transcript.id == victim["transcript_id"])).all() == []
        hit = db.execute(update(Transcript).where(Transcript.id == victim["transcript_id"]).values(filename="pwned"))
        assert hit.rowcount == 0  # type: ignore[attr-defined]
        db.add(
            Transcript(organization_id=victim["org_id"], project_id=victim["project_id"], filename="x", storage_key="x")
        )
        with pytest.raises(TenancyError, match="another organization"):
            db.flush()

    with SessionLocal() as unscoped, pytest.raises(TenancyError):  # forgot to scope -> error, not a leak
        unscoped.scalars(select(Transcript)).all()

    with tenant_session(victim["org_id"]) as db:
        assert db.get_one(Transcript, victim["transcript_id"]).filename == "transcript_1.vtt"


def test_new_rows_are_stamped_with_the_session_org(other_tenant: TenantCtx) -> None:
    with tenant_session(other_tenant.org_id) as db:
        key = create_key(db, other_tenant.org_id, "ci")
        db.commit()
    principal = verify(key)
    assert principal is not None and principal.org_id == other_tenant.org_id
