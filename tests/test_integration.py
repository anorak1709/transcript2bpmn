"""End to end against the compose services (Postgres, MinIO, Redis), LLM faked.

Skipped when the services aren't up: run `make up` (or `docker compose up -d postgres redis minio`)
and `make migrate` first.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.db.models import Job, Transcript
from app.db.tenancy import tenant_session
from app.models.transcript import UNKNOWN_SPEAKER, Segment
from app.pipeline.run import model_to_bpmn
from app.pipeline.transcribe import Transcriber, Transcription
from tests.conftest import GOLD, FakeLLM, TenantCtx, gold_model, needs_services

pytestmark = needs_services


def test_upload_process_map_roundtrip(tenant: TenantCtx) -> None:
    vtt = (GOLD / "01_invoice_approval" / "transcript.vtt").read_bytes()
    r = tenant.upload("walkthrough.vtt", vtt)
    assert r.status_code == 201, r.text
    transcript_id = r.json()["id"]

    job = tenant.process(transcript_id, FakeLLM(gold_model("01_invoice_approval")))
    assert job["status"] == "done", job["error"]
    assert tenant.queue.jobs == [("process_transcript", job["id"])]
    m = tenant.client.get(f"/maps/{job['map_id']}").json()

    assert m["bpmn_xml"] == model_to_bpmn(gold_model("01_invoice_approval"))  # XSD-validated inside
    with tenant_session(tenant.org_id) as db:
        segments = db.get_one(Transcript, transcript_id).segments or []
    valid = {s["segment_id"] for s in segments}
    assert all(n["source_segment_ids"] and set(n["source_segment_ids"]) <= valid for n in m["model"]["nodes"])
    assert tenant.client.get(f"/editor/{job['map_id']}").status_code == 200

    # The first meeting also seeds the project's merged map, with transcript-qualified citations.
    project = tenant.client.get(f"/projects/{tenant.project_id}").json()
    merged = tenant.client.get(f"/maps/{project['merged_map_id']}").json()
    assert merged["transcript_id"] is None
    assert all(c.startswith(f"{transcript_id}:") for n in merged["model"]["nodes"] for c in n["source_segment_ids"])
    assert {s["segment_id"] for s in merged["segments"]} == {f"{transcript_id}:{s}" for s in valid}


def test_bad_uploads_are_rejected(tenant: TenantCtx) -> None:
    assert tenant.upload("a.mp3", b"x").status_code == 400
    assert tenant.upload("a.txt", b"  \n\n").status_code == 400
    assert tenant.client.post("/transcripts/nope/process").status_code == 404
    assert tenant.upload("a.txt", b"Ann: hi", project_id="nope").status_code == 404


def test_failed_pipeline_marks_job_failed(tenant: TenantCtx) -> None:
    tid = tenant.upload("t.txt", b"Ann: We ship it.").json()["id"]

    class Boom(FakeLLM):
        def structured(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("LLM down")

    job = tenant.process(tid, Boom(gold_model("01_invoice_approval")))
    assert job["status"] == "failed" and "LLM down" in job["error"]


def _wav(tmp_path: Path, seconds: int = 3) -> bytes:
    path = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=d={seconds}", str(path)], check=True)
    return path.read_bytes()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_audio_upload_transcribes_then_runs_pipeline(tenant: TenantCtx, tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    class FakeTranscriber(Transcriber):
        def transcribe(self, audio_path: Path) -> Transcription:
            assert audio_path.read_bytes()[:4] == b"RIFF"  # the stored original came back from S3
            with tenant_session(tenant.org_id) as db:
                job = db.query(Job).filter(Job.transcript_id == tid).one()
                seen["status"] = job.status
            texts = ["A supplier invoice lands in the AP inbox.", "We enter it into the ERP.", "Then we pay it."]
            segs = [
                Segment(segment_id="", speaker=UNKNOWN_SPEAKER, start_ts=i, end_ts=i + 1, text=t)
                for i, t in enumerate(texts)
            ]
            return Transcription(segments=segs, diarization_available=False)

    r = tenant.upload("meeting.wav", _wav(tmp_path))
    assert r.status_code == 201, r.text
    assert abs(r.json()["duration_seconds"] - 3) < 0.1 and r.json()["segment_count"] is None
    tid = r.json()["id"]

    job = tenant.process(tid, FakeLLM(gold_model("01_invoice_approval")), FakeTranscriber())

    assert seen["status"] == "transcribing"
    assert job["status"] == "done", job["error"]
    with tenant_session(tenant.org_id) as db:
        t = db.get_one(Transcript, tid)
        assert t.diarization_available is False
        assert [s["segment_id"] for s in t.segments or []] == ["s1", "s2", "s3"]  # not merged


def test_non_audio_with_audio_extension_is_rejected(tenant: TenantCtx) -> None:
    if shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg not installed")
    r = tenant.upload("fake.mp3", b"definitely not audio")
    assert r.status_code == 400 and "audio" in r.json()["detail"]
