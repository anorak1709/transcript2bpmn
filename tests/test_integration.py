"""End to end against the compose services (Postgres, MinIO, Redis), LLM faked.

Skipped when the services aren't up: run `make up` (or `docker compose up -d postgres redis minio`)
and `make migrate` first.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import storage
from app.db.base import SessionLocal
from app.db.models import Job, Transcript
from app.main import app
from app.models.transcript import UNKNOWN_SPEAKER, Segment
from app.pipeline.run import model_to_bpmn
from app.pipeline.transcribe import Transcriber, Transcription
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


def _wav(tmp_path: Path, seconds: int = 3) -> bytes:
    path = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=d={seconds}", str(path)], check=True)
    return path.read_bytes()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_audio_upload_transcribes_then_runs_pipeline(tmp_path: Path) -> None:
    class FakeTranscriber(Transcriber):
        seen_status: str | None = None

        def transcribe(self, audio_path: Path) -> Transcription:
            assert audio_path.read_bytes()[:4] == b"RIFF"  # the stored original came back from S3
            with SessionLocal() as db:
                FakeTranscriber.seen_status = db.get_one(Job, job_id).status
            texts = ["A supplier invoice lands in the AP inbox.", "We enter it into the ERP.", "Then we pay it."]
            segs = [
                Segment(segment_id="", speaker=UNKNOWN_SPEAKER, start_ts=i, end_ts=i + 1, text=t)
                for i, t in enumerate(texts)
            ]
            return Transcription(segments=segs, diarization_available=False)

    with TestClient(app) as client:
        app.state.arq = RecordingQueue()
        r = client.post("/transcripts", files={"file": ("meeting.wav", _wav(tmp_path), "audio/wav")})
        assert r.status_code == 201, r.text
        assert abs(r.json()["duration_seconds"] - 3) < 0.1 and r.json()["segment_count"] is None
        tid = r.json()["id"]
        job_id = client.post(f"/transcripts/{tid}/process").json()["id"]

        run_job(job_id, FakeLLM(gold_model("01_invoice_approval")), FakeTranscriber())

        assert FakeTranscriber.seen_status == "transcribing"
        job = client.get(f"/jobs/{job_id}").json()
        assert job["status"] == "done", job["error"]
        with SessionLocal() as db:
            t = db.get_one(Transcript, tid)
            assert t.diarization_available is False
            assert [s["segment_id"] for s in t.segments or []] == ["s1", "s2", "s3"]  # not merged


def test_non_audio_with_audio_extension_is_rejected() -> None:
    if shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg not installed")
    with TestClient(app) as client:
        r = client.post("/transcripts", files={"file": ("fake.mp3", b"definitely not audio", "audio/mpeg")})
        assert r.status_code == 400 and "audio" in r.json()["detail"]
