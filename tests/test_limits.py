"""Rate limits (real Redis, via the app lifespan) and monthly quotas."""

import uuid

import pytest

from app.core.config import get_settings
from app.db.models import Organization
from app.db.tenancy import system_session
from tests.conftest import GOLD, make_tenant, needs_services

pytestmark = needs_services


@pytest.fixture(autouse=True)
def private_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    # Lifespan = real arq pool; keep these jobs away from any running worker.
    monkeypatch.setattr(get_settings(), "job_queue", f"arq:test:{uuid.uuid4().hex[:8]}")


def test_api_rate_limit_is_per_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 3)
    a, b = make_tenant(), make_tenant()
    with a.client:  # one app lifespan (one Redis pool) serves both clients
        codes = [a.client.get("/projects").status_code for _ in range(4)]
        assert codes[:3] == [200, 200, 200] and codes[3] == 429
        r = a.client.get("/projects")
        assert r.status_code == 429 and 0 < int(r.headers["retry-after"]) <= 60
        other_key = {"Authorization": f"Bearer {b.key}"}  # same client/event loop, different key
        assert a.client.get("/projects", headers=other_key).status_code == 200  # its own budget


def test_heavy_routes_have_a_tighter_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_heavy_per_minute", 1)
    t = make_tenant()
    vtt = (GOLD / "01_invoice_approval" / "transcript.vtt").read_bytes()
    with t.client:
        assert t.upload("a.vtt", vtt).status_code == 201
        assert t.upload("b.vtt", vtt).status_code == 429
        assert t.client.get(f"/projects/{t.project_id}").status_code == 200  # light calls unaffected


def test_monthly_quota() -> None:
    t = make_tenant()
    with system_session() as db:
        db.get_one(Organization, t.org_id).monthly_jobs_quota = 1
        db.commit()
    vtt = (GOLD / "01_invoice_approval" / "transcript.vtt").read_bytes()
    tid = t.upload("a.vtt", vtt).json()["id"]
    with t.client:
        assert t.client.post(f"/transcripts/{tid}/process").status_code == 202
        r = t.client.post(f"/transcripts/{tid}/process")
        assert r.status_code == 429 and "quota" in r.json()["detail"]
        usage = t.client.get("/usage").json()
        assert usage["jobs_this_month"] == 1 and usage["monthly_jobs_quota"] == 1
