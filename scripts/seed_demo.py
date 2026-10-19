"""Seed a demo workspace so the web app has something to explore without an LLM key.

    uv run python scripts/seed_demo.py [--api http://localhost:8000]

Creates an organization + API key (printed once) and two projects, each with two meetings
from eval/gold_merge. Files are uploaded through the real API; processing runs the real
pipeline (normalize, validate, BPMN, multi-meeting merge, conflicts) in this process, with the
LLM replaced by the gold extraction for each meeting (the test suite's FakeLLM). So the maps
are what a perfect extraction would give, not a live model's output.
"""

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.auth import create_key, create_org  # noqa: E402
from app.db.models import Job  # noqa: E402
from app.db.tenancy import system_session, tenant_session  # noqa: E402
from app.models.process import ProcessModel  # noqa: E402
from app.workers.jobs import run_job  # noqa: E402
from tests.conftest import FakeLLM  # noqa: E402

CASES = [
    ("Supplier invoice approval", ROOT / "eval/gold_merge/01_invoice_two_meetings", 30),
    ("New employee onboarding", ROOT / "eval/gold_merge/02_onboarding_order_conflict", None),
]
# Speaker roles to tag, so disagreements show who backs which side.
ROLES = {"Supplier invoice approval": {"Marco": "owner", "Priya": "performer", "Sana": "performer"}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--org", default="Demo workspace")
    args = ap.parse_args()

    with system_session() as db:
        org = create_org(db, args.org)
        key = create_key(db, org.id, "demo")
        db.commit()
    http = httpx.Client(base_url=args.api, headers={"Authorization": f"Bearer {key}"}, timeout=60)

    for name, case, retention in CASES:
        project = http.post("/projects", json={"name": name, "retention_days": retention}).raise_for_status().json()
        for k, transcript in enumerate(sorted(case.glob("transcript_*.*")), 1):
            t = (
                http.post(
                    f"/projects/{project['id']}/transcripts", files={"file": (transcript.name, transcript.read_bytes())}
                )
                .raise_for_status()
                .json()
            )
            with tenant_session(org.id) as db:  # a job row, run here instead of via the queue
                job = Job(transcript_id=t["id"], status="queued")
                db.add(job)
                db.commit()
                job_id = job.id
            model = ProcessModel.model_validate_json((case / f"model_{k}.json").read_text())
            run_job(job_id, FakeLLM(model))
        if (case / "policy.txt").exists():  # the written policy, to compare the map against
            doc = case / "policy.txt"
            t = (
                http.post(
                    f"/projects/{project['id']}/transcripts?purpose=policy",
                    files={"file": ("invoice-policy.txt", doc.read_bytes())},
                )
                .raise_for_status()
                .json()
            )
            with tenant_session(org.id) as db:
                job = Job(transcript_id=t["id"], status="queued")
                db.add(job)
                db.commit()
                job_id = job.id
            run_job(job_id, FakeLLM(ProcessModel.model_validate_json((case / "policy_model.json").read_text())))
        for speaker, role in ROLES.get(name, {}).items():
            http.put(f"/projects/{project['id']}/speakers/{speaker}", json={"role": role}).raise_for_status()
        p = http.get(f"/projects/{project['id']}").raise_for_status().json()
        statuses = [x["latest_job"]["status"] for x in p["transcripts"]]
        print(
            f"  {name}: files {statuses}, {p['open_conflicts']} disagreement(s), "
            f"{p['open_policy_differences']} policy difference(s) to review"
        )

    print(f"\norganization: {org.id}\napi key (shown once): {key}\nopen: {args.api}/app/")


if __name__ == "__main__":
    main()
