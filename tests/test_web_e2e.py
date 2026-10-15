"""The web app in a real browser against the real server (in-process uvicorn), LLM faked.

Covers the main workflow end to end: sign in -> project -> upload two meetings -> live job
status -> merged map in the editor -> apply a conflict option -> source quotes -> chat edit
-> settings (API keys). Fails on any console error, which includes CSP violations.

Needs: compose services, a built frontend (`make web-build`), and Chromium
(`playwright install chromium`) or a local Chrome.
"""

import re
import shutil
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from app.api.maps import get_llm
from app.core.config import get_settings
from app.main import WEB, app
from app.models.process import ProcessModel
from app.pipeline.edit import EditPlan
from app.workers.jobs import run_job
from tests.conftest import FakeLLM, needs_services
from tests.test_validate import ScriptedLLM

CASE = Path(__file__).parent.parent / "eval" / "gold_merge" / "01_invoice_two_meetings"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SHOTS = Path(__file__).parent.parent / ".build"

pytestmark = [
    needs_services,
    pytest.mark.skipif(not (WEB / "index.html").exists(), reason="frontend not built (make web-build)"),
]


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setattr(get_settings(), "job_queue", f"arq:test:{uuid.uuid4().hex[:8]}")  # no worker races us
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)
    app.dependency_overrides.clear()


def _browser(p: Any) -> Any:
    if shutil.which("chromium") is None and CHROME.exists():
        return p.chromium.launch(channel="chrome")
    return p.chromium.launch()


class Workspace:
    """An org + key + project, created through the live server over HTTP (like any client)."""

    def __init__(self, server: str) -> None:
        import httpx

        from app.auth import create_key, create_org
        from app.db.tenancy import system_session

        with system_session() as db:
            org = create_org(db, f"E2E {uuid.uuid4().hex[:6]}")
            self.key = create_key(db, org.id)
            db.commit()
        self.http = httpx.Client(base_url=server, headers={"Authorization": f"Bearer {self.key}"})
        self.project_id = self.http.post("/projects", json={"name": "Invoices"}).json()["id"]


def _process_latest(t: Workspace, filename: str, model_file: str) -> None:
    """The UI uploads and enqueues; stand in for the worker with a fake LLM."""
    project = t.http.get(f"/projects/{t.project_id}").json()
    transcript = next(x for x in project["transcripts"] if x["filename"] == filename)
    model = ProcessModel.model_validate_json((CASE / model_file).read_text())
    run_job(transcript["latest_job"]["id"], FakeLLM(model))


def test_main_workflow_in_the_browser(server: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    t = Workspace(server)
    errors: list[str] = []
    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        def on_console(msg: Any) -> None:
            if msg.type == "error":
                errors.append(msg.text)

        page.on("console", on_console)
        page.on("pageerror", lambda e: errors.append(str(e)))

        # Sign in
        page.goto(f"{server}/")
        expect(page.get_by_role("heading", name="Transcript to BPMN")).to_be_visible()
        page.get_by_label("API key").fill("t2b_wrong_key")
        page.get_by_role("button", name="Open the workspace").click()
        expect(page.get_by_text("That key isn't valid or was revoked.")).to_be_visible()
        page.get_by_label("API key").fill(t.key)
        page.get_by_role("button", name="Open the workspace").click()

        # Projects list -> project
        expect(page.get_by_role("heading", name="Processes")).to_be_visible()
        # The design system is what's actually rendered (MASTER.md): paper, ink, serif, oxblood.
        style = page.evaluate(
            """() => {
              const cs = (el) => getComputedStyle(el)
              const h1 = document.querySelector("h1")
              const primary = [...document.querySelectorAll("button")]
                .find((b) => b.textContent.includes("New process"))
              return { bg: cs(document.body).backgroundColor, h1: cs(h1).fontFamily, body: cs(document.body).fontFamily,
                       primary: cs(primary).backgroundColor }
            }"""
        )
        assert style["bg"] == "rgb(253, 251, 247)" and style["primary"] == "rgb(139, 46, 42)", style
        assert "EB Garamond" in style["h1"] and "Lato" in style["body"], style
        page.keyboard.press("Tab")  # keyboard focus shows the 2px oxblood ring
        ring = page.evaluate("() => getComputedStyle(document.activeElement).outlineColor")
        assert ring == "rgb(139, 46, 42)", ring
        page.get_by_role("link", name="Invoices").click()
        expect(page.get_by_role("heading", name="Invoices")).to_be_visible()

        # Upload meeting 1: UI uploads + enqueues, status goes live
        page.locator("#upload-input").set_input_files(str(CASE / "transcript_1.vtt"))
        expect(page.get_by_text("transcript_1.vtt uploaded")).to_be_visible()
        expect(page.get_by_role("cell", name="transcript_1.vtt", exact=True)).to_be_visible()
        expect(page.get_by_text(re.compile(r"^Queued"))).to_be_visible()
        _process_latest(t, "transcript_1.vtt", "model_1.json")
        expect(page.get_by_text("Done")).to_be_visible(timeout=10_000)  # polling picked it up

        # Meeting 2 -> disagreements appear
        page.locator("#upload-input").set_input_files(str(CASE / "transcript_2.txt"))
        expect(page.get_by_role("cell", name="transcript_2.txt", exact=True)).to_be_visible()
        _process_latest(t, "transcript_2.txt", "model_2.json")
        expect(page.get_by_role("button", name="Settle as Treasury")).to_be_visible(timeout=10_000)
        page.screenshot(path=str(SHOTS / "e2e-project.png"))

        # Merged map in the editor
        page.get_by_role("link", name="Open the map").click()
        expect(page.locator(".bpmn-canvas svg").first).to_be_visible()
        expect(page.locator('.bpmn-canvas [data-element-id="Node_t_bank"]')).to_be_visible()
        expect(page.get_by_text(re.compile(r"^v2 ·"))).to_be_visible()

        # Apply a conflict option from the Questions tab
        page.get_by_role("tab", name="Questions (3)").click()
        page.get_by_role("button", name="Settle as Treasury").click()
        expect(page.get_by_text("Applied to the map")).to_be_visible()
        expect(page.get_by_text(re.compile(r"^v3 ·"))).to_be_visible()

        # Select a step on the canvas -> its transcript quotes
        page.locator('.bpmn-canvas [data-element-id="Node_t_pay"]').click()
        page.get_by_role("tab", name="Step").click()
        expect(page.get_by_text("payment run picks it up on Friday")).to_be_visible()
        expect(page.get_by_text("treasury pays the supplier")).to_be_visible()  # second meeting's quote too

        # Chat edit (LLM faked via the dependency override)
        plan = EditPlan.model_validate({"reply": "Renamed the payment step.", "ops": [
            {"op": "rename_node", "node_id": "t_pay", "name": "Release supplier payment"}]})  # fmt: skip
        app.dependency_overrides[get_llm] = lambda: ScriptedLLM(plan)
        page.get_by_label("Describe a change").fill("call it release supplier payment")
        page.keyboard.press("Enter")
        expect(page.get_by_text("Renamed the payment step.")).to_be_visible()
        expect(page.get_by_text(re.compile(r"^v4 ·"))).to_be_visible()
        page.screenshot(path=str(SHOTS / "e2e-editor.png"))

        # Concurrent edit: another client changes the map behind this editor's back (v4 -> v3).
        map_id = page.url.rstrip("/").split("/")[-1]
        assert t.http.post(f"/maps/{map_id}/undo", headers={"If-Match": '"4"'}).status_code == 200
        page.get_by_role("button", name="Undo").click()  # the editor still thinks it's on v4
        expect(page.get_by_role("alertdialog", name="Someone else changed this map")).to_be_visible()
        expect(page.get_by_text("you have v4, it's now v3")).to_be_visible()
        page.get_by_role("button", name="Reload latest").click()
        expect(page.get_by_role("alertdialog")).to_be_hidden()
        expect(page.get_by_text(re.compile(r"^v3 ·"))).to_be_visible()
        assert t.http.get(f"/maps/{map_id}").json()["version"] == 3  # the stale undo wrote nothing
        page.screenshot(path=str(SHOTS / "e2e-reloaded.png"))

        # Settings: create a key, shown once
        page.get_by_role("link", name="Settings").click()
        page.get_by_label("New key name").fill("e2e")
        page.get_by_role("button", name="Create key").click()
        expect(page.get_by_text("Copy this key now")).to_be_visible()
        expect(page.locator("code").filter(has_text="t2b_").first).to_be_visible()

        page.screenshot(path=str(SHOTS / "e2e-settings.png"), full_page=True)
        browser.close()

    # Exactly two failed requests are part of the script: the wrong key at sign-in (401) and
    # the deliberately stale undo (412). Anything else (incl. CSP violations) fails the test.
    expected = ("status of 401", "status of 412")
    unexpected = [e for e in errors if not any(x in e for x in expected)]
    assert unexpected == [], unexpected
    assert sorted(x for e in errors for x in expected if x in e) == list(expected)


def test_spa_routes_and_redirects(server: str) -> None:
    import httpx

    with httpx.Client(base_url=server, follow_redirects=False) as c:
        assert c.get("/").headers["location"] == "/app/"
        assert c.get("/editor/abc").headers["location"] == "/app/maps/abc"
        assert c.get("/settings").headers["location"] == "/app/settings"
        deep = c.get("/app/projects/some-id")  # client-side route -> index.html
        assert deep.status_code == 200 and '<div id="root">' in deep.text
        assert "script-src 'self'" in deep.headers["content-security-policy"]
        asset = next((WEB / "assets").glob("index-*.js")).name
        r = c.get(f"/app/assets/{asset}")
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        assert c.get("/app/../../app/main.py").status_code in (200, 404)  # never the source file
        assert "FastAPI" not in c.get("/app/..%2f..%2fmain.py").text
