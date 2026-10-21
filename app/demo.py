"""Demo mode and public sandboxes: the product without AI.

- DEMO_MODE=true (a demo deployment): no request may reach an AI provider.
- Sandbox workspaces (DEMO_SANDBOXES=true): `POST /demo` gives each visitor a fresh copy of the
  sample workspace, built here with the gold extractions (no AI), deleted after SANDBOX_HOURS.
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import storage
from app.core.config import get_settings
from app.db.models import ApiKey, AuditLog, Correction, Invite, Job, Membership, Organization, Project, Transcript
from app.db.tenancy import system_session, tenant_session
from app.models.process import ProcessModel

log = logging.getLogger(__name__)

GOLD = Path(__file__).resolve().parent.parent / "eval" / "gold_merge"


def ai_allowed(org: Organization | None) -> bool:
    return not get_settings().demo_mode and not (org is not None and org.sandbox_expires_at is not None)


def require_ai(db: Session, org_id: str) -> None:
    """Refuse anything that would call an AI provider in demo mode or a demo sandbox."""
    if not ai_allowed(db.get(Organization, org_id)):
        raise HTTPException(
            403, "This is the demo: AI processing is switched off. Explore the sample processes instead."
        )


# --- The sample workspace -------------------------------------------------------------------

SAMPLES = [  # (process, folder in eval/gold_merge, retention days, speaker roles)
    (
        "Supplier invoice approval",
        "01_invoice_two_meetings",
        30,
        {"Marco": "owner", "Priya": "performer", "Sana": "performer"},
    ),
    ("New employee onboarding", "02_onboarding_order_conflict", None, {}),
]


def _add_file(org_id: str, project_id: str, path: Path, filename: str, purpose: str, model: ProcessModel) -> None:
    """Upload + process one file the way the app does, with the stand-in AI (no network)."""
    from app.stand_in import FakeLLM
    from app.workers.jobs import run_job

    with tenant_session(org_id) as db:
        t = Transcript(project_id=project_id, filename=filename, storage_key="", purpose=purpose)
        db.add(t)
        db.flush()
        t.storage_key = f"{storage.project_prefix(org_id, project_id)}transcripts/{t.id}/{filename}"
        storage.put(t.storage_key, path.read_bytes())
        job = Job(transcript_id=t.id, status="queued")
        db.add(job)
        db.commit()
        job_id = job.id
    run_job(job_id, FakeLLM(model))


def build_sample(org_id: str) -> None:
    """Fill a workspace with the sample processes: two meetings each, a policy document for the
    invoice process, speaker roles. Everything a visitor can explore without AI."""
    for name, folder, retention, roles in SAMPLES:
        case = GOLD / folder
        with tenant_session(org_id) as db:
            p = Project(name=name, retention_days=retention, speaker_roles=roles)
            db.add(p)
            db.commit()
            pid = p.id
        for k, path in enumerate(sorted(case.glob("transcript_*.*")), 1):
            model = ProcessModel.model_validate_json((case / f"model_{k}.json").read_text())
            _add_file(org_id, pid, path, path.name, "meeting", model)
        if (case / "policy.txt").exists():
            model = ProcessModel.model_validate_json((case / "policy_model.json").read_text())
            _add_file(org_id, pid, case / "policy.txt", "invoice-policy.txt", "policy", model)


def create_sandbox() -> tuple[str, str]:
    """A fresh demo workspace for one visitor. Returns (org id, session key)."""
    from app.auth import create_key, create_org

    hours = get_settings().sandbox_hours
    with system_session() as db:
        org = create_org(db, "Demo sandbox")
        org.sandbox_expires_at = datetime.now(UTC) + timedelta(hours=hours)
        key = create_key(db, org.id, "Demo visitor", expires_at=org.sandbox_expires_at)
        db.commit()
        org_id = org.id
    build_sample(org_id)
    return org_id, key


def purge_sandboxes(now: datetime | None = None) -> int:
    """Delete expired demo sandboxes completely (daily, from the worker). Returns how many."""
    from app.projects import delete_project

    now = now or datetime.now(UTC)
    with system_session() as db:
        expired = list(
            db.scalars(
                select(Organization.id).where(
                    Organization.sandbox_expires_at.is_not(None), Organization.sandbox_expires_at < now
                )
            )
        )
    for org_id in expired:
        with tenant_session(org_id) as db:
            for p in db.scalars(select(Project)).all():
                delete_project(db, p)
            db.commit()
        with system_session() as db:
            for model in (Correction, Invite, Membership, AuditLog, ApiKey):
                db.execute(delete(model).where(model.organization_id == org_id))
            db.execute(delete(Organization).where(Organization.id == org_id))
            db.commit()
    if expired:
        log.info("purged %d expired demo sandbox(es)", len(expired))
    return len(expired)
