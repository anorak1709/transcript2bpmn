"""Key management, security headers / CSP, CORS, Prometheus metrics."""

import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import CSP, STATIC, app
from app.metrics import timed_llm_call
from tests.conftest import TenantCtx, needs_services


@needs_services
def test_key_lifecycle(tenant: TenantCtx) -> None:
    keys = tenant.client.get("/keys").json()
    assert len(keys) == 1 and keys[0]["current"] is True

    new = tenant.client.post("/keys", json={"name": "ci"})
    assert new.status_code == 201 and new.json()["key"].startswith(f"t2b_{new.json()['prefix']}_")
    ci = TestClient(app, headers={"Authorization": f"Bearer {new.json()['key']}"})
    assert ci.get("/projects").status_code == 200
    assert "key" not in tenant.client.get("/keys").json()[1]  # never listed again

    assert tenant.client.delete(f"/keys/{new.json()['id']}").json()["revoked_at"]
    assert ci.get("/projects").status_code == 401
    assert tenant.client.delete(f"/keys/{keys[0]['id']}").status_code == 409  # last active key: refused
    actions = [a["action"] for a in tenant.client.get("/audit").json()]
    assert {"create_key", "revoke_key"} <= set(actions)


def test_security_headers_and_csp() -> None:
    client = TestClient(app)
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert "content-security-policy" not in h  # JSON doesn't need one
    for page in ("/editor/x", "/settings"):
        r = client.get(page)
        assert r.status_code == 200 and r.headers["content-security-policy"] == CSP
    assert "script-src 'self';" in CSP and "unsafe-inline" not in CSP.split("script-src")[1].split(";")[0]
    assert client.get("/health", headers={"x-forwarded-proto": "https"}).status_code == 200


def test_web_app_has_no_third_party_or_inline_code() -> None:
    import re

    from app.main import WEB

    if not (WEB / "index.html").exists():
        pytest.skip("frontend not built (make web-build)")
    html = (WEB / "index.html").read_text()
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) is None  # every script is an external file
    assert "unpkg" not in html and "cdn" not in html.lower()
    client = TestClient(app)
    for src in re.findall(r'(?:src|href)="(/app/assets/[^"]+)"', html):
        assert client.get(src).status_code == 200, src
    bundles = " ".join(p.read_text(errors="ignore") for p in (WEB / "assets").glob("*.js"))
    assert "unpkg.com" not in bundles  # bpmn-js is bundled, nothing fetched from a CDN
    assert (STATIC / "vendor" / "bpmn-viewer.production.min.js").exists()  # server-side export renderer


def test_cors_is_off_by_default_and_configurable() -> None:
    preflight = {"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    assert "access-control-allow-origin" not in TestClient(app).options("/projects", headers=preflight).headers

    probe = (
        "from fastapi.testclient import TestClient; from app.main import app; import json;"
        "h = TestClient(app).options('/projects', headers={'Origin': 'https://app.acme.com',"
        " 'Access-Control-Request-Method': 'GET'}).headers; print(json.dumps(dict(h)))"
    )
    env = {**os.environ, "CORS_ORIGINS": '["https://app.acme.com"]'}
    out = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, check=True)
    headers = json.loads(out.stdout.strip().splitlines()[-1])
    assert headers["access-control-allow-origin"] == "https://app.acme.com"


def test_metrics_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    assert client.get("/metrics").status_code == 404  # disabled without a token
    monkeypatch.setattr(get_settings(), "metrics_token", "s3cret")
    assert client.get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 404

    client.get("/maps/some-real-looking-id")  # 401, but counted under the route template
    with pytest.raises(RuntimeError), timed_llm_call("extract"):
        raise RuntimeError("provider down")
    body = client.get("/metrics", headers={"Authorization": "Bearer s3cret"}).text
    assert 't2b_http_requests_total{method="GET",route="/maps/{map_id}",status="401"}' in body
    assert "some-real-looking-id" not in body  # ids never become labels
    assert 't2b_llm_calls_total{outcome="error",role="extract"}' in body


def test_worker_exposes_metrics_port() -> None:
    from app.workers.settings import WorkerSettings, startup

    assert WorkerSettings.on_startup is startup  # binds METRICS_PORT; checked live in the compose run
