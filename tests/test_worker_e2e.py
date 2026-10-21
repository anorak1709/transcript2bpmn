"""The real queue: API enqueues into Redis, a real arq Worker picks the job up and runs it.

Other tests call run_job() directly; this one proves the wiring between them. It uses its own
queue name so a worker container running at the same time can't steal the job.
"""

import uuid
from pathlib import Path

import pytest
from arq.connections import RedisSettings
from arq.worker import Worker

from app.core.config import get_settings
from app.models.process import ProcessModel
from app.workers import jobs
from app.workers.settings import WorkerSettings
from tests.conftest import FakeLLM, make_tenant, needs_services

pytestmark = needs_services
CASE = Path(__file__).parent.parent / "eval" / "gold_merge" / "01_invoice_two_meetings"


def test_job_runs_through_redis_and_a_real_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = f"arq:test:{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(get_settings(), "job_queue", queue)
    model = ProcessModel.model_validate_json((CASE / "model_1.json").read_text())
    monkeypatch.setattr(jobs, "LiteLLMProvider", lambda: FakeLLM(model))  # the only fake: no LLM key here

    t = make_tenant()
    tid = t.upload("transcript_1.vtt", (CASE / "transcript_1.vtt").read_bytes()).json()["id"]
    with t.client:  # runs the app lifespan -> real arq Redis pool replaces the test queue
        job = t.client.post(f"/transcripts/{tid}/process").json()
        assert t.client.get(f"/jobs/{job['id']}").json()["status"] == "queued"

        worker = Worker(
            functions=WorkerSettings.functions,
            redis_settings=RedisSettings.from_dsn(get_settings().redis_url),
            queue_name=queue,
            burst=True,  # process what's queued, then stop
            poll_delay=0.1,
            handle_signals=False,
        )
        worker.run()
        assert (worker.jobs_complete, worker.jobs_failed) == (1, 0)

        done = t.client.get(f"/jobs/{job['id']}").json()
        assert done["status"] == "done", done["error"]
        assert t.client.get(f"/projects/{t.project_id}").json()["merged_map_id"]


def test_retention_cron_is_scheduled() -> None:
    by_job = {c.coroutine: c for c in WorkerSettings.cron_jobs}
    assert by_job[jobs.retention].hour == 3 and by_job[jobs.retention].minute == 0
    assert by_job[jobs.purge_demo_sandboxes].minute == 15  # hourly
