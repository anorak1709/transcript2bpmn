"""End to end against the compose services (Postgres, MinIO, Redis), LLM faked.

Skipped when the services aren't up: run `make up` (or `docker compose up -d postgres redis minio`)
and `make migrate` first.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import storage
from app.db.base import SessionLocal
from app.db.models import Transcript
from app.main import app
from app.pipeline.run import model_to_bpmn
from app.workers.jobs import run_job
from tests.conftest import GOLD, FakeLLM, gold_model


def _services_up() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("select 1 from transcripts limit 1"))
        storage._client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _services_up(), reason="compose services not running / not migrated")


class RecordingQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[Any, ...]] = []

    async def enqueue_job(self, *args: Any, **kwargs: Any) -> None:
        self.jobs.append(args)


def test_upload_process_map_roundtrip() -> None:
    vtt = (GOLD / "01_invoice_approval" / "transcript.vtt").read_bytes()
    with TestClient(app) as client:
        queue = RecordingQueue()
        app.state.arq = queue  # don't let a running worker race us with a real LLM

        r = client.post("/transcripts", files={"file": ("walkthrough.vtt", vtt, "text/vtt")})
        assert r.status_code == 201, r.text
        transcript_id = r.json()["id"]

        r = client.post(f"/transcripts/{transcript_id}/process")
        assert r.status_code == 202
        job_id = r.json()["id"]
        assert queue.jobs == [("process_transcript", job_id)]

        run_job(job_id, FakeLLM(gold_model("01_invoice_approval")))

        job = client.get(f"/jobs/{job_id}").json()
        assert job["status"] == "done", job["error"]
        m = client.get(f"/maps/{job['map_id']}").json()

        assert m["bpmn_xml"] == model_to_bpmn(gold_model("01_invoice_approval"))  # XSD-validated inside
        with SessionLocal() as db:
            segments = db.get_one(Transcript, transcript_id).segments or []
        valid = {s["segment_id"] for s in segments}
        assert all(n["source_segment_ids"] and set(n["source_segment_ids"]) <= valid for n in m["model"]["nodes"])

        assert client.get(f"/viewer/{job['map_id']}").status_code == 200


def test_bad_uploads_are_rejected() -> None:
    with TestClient(app) as client:
        assert client.post("/transcripts", files={"file": ("a.mp3", b"x")}).status_code == 400
        assert client.post("/transcripts", files={"file": ("a.txt", b"  \n\n")}).status_code == 400
        assert client.post("/transcripts/nope/process").status_code == 404


def test_failed_pipeline_marks_job_failed() -> None:
    with TestClient(app) as client:
        app.state.arq = RecordingQueue()
        tid = client.post("/transcripts", files={"file": ("t.txt", b"Ann: We ship it.")}).json()["id"]
        job_id = client.post(f"/transcripts/{tid}/process").json()["id"]

        class Boom(FakeLLM):
            def structured(self, *a: Any, **k: Any) -> Any:
                raise RuntimeError("LLM down")

        run_job(job_id, Boom(gold_model("01_invoice_approval")))
        job = client.get(f"/jobs/{job_id}").json()
        assert job["status"] == "failed" and "LLM down" in job["error"]
