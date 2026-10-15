"""Project-level operations: merging meetings, deleting a project, retention."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import maps, storage
from app.audit import audit
from app.db.models import Conflict, Job, MapVersion, ProcessMap, Project, Transcript
from app.db.tenancy import bind, system_session
from app.llm.provider import LLMProvider
from app.models.process import ProcessModel
from app.pipeline.merge import merge, qualify

log = logging.getLogger(__name__)


def merge_into_project(
    db: Session, project: Project, transcript: Transcript, model: ProcessModel, llm: LLMProvider
) -> ProcessMap:
    """Fold one transcript's model into the project's merged map. The first transcript seeds
    it; later ones are merged with patch ops on top of whatever the user has edited."""
    new = qualify(model, transcript.id)
    # Merges into one project run one at a time: lock the project row and re-read it, so two
    # meetings finishing together can't both create a merged map or merge from a stale base.
    locked = db.get(Project, project.id, with_for_update=True, populate_existing=True)
    assert locked is not None
    project = locked
    if project.merged_map_id is None:
        pmap = maps.create_map(db, project.id, None, new, source="merge")
        project.merged_map_id = pmap.id
        return pmap

    locked_map = maps.lock_map(db, project.merged_map_id)  # and wait for any user edit in progress
    assert locked_map is not None
    pmap = locked_map
    result = merge(llm, ProcessModel.model_validate(pmap.model), new, transcript.id)
    for c in result.conflicts:
        db.add(
            Conflict(
                id=c.id,
                project_id=project.id,
                kind=c.kind,
                description=c.description,
                options=c.options,
                sources=c.sources,
                node_ids=c.node_ids,
            )
        )
    maps.commit_version(
        db, pmap, result.model, "merge", maps.current_positions(pmap), result.ops, f"Merged {transcript.filename}"
    )
    audit(
        db, "merge", "map", pmap.id, transcript_id=transcript.id, ops=len(result.ops), conflicts=len(result.conflicts)
    )
    return pmap


def delete_project(db: Session, project: Project) -> dict[str, int]:
    """Remove every row and stored object of a project. The audit log keeps metadata-only
    entries (including this deletion), by design."""
    counts = {"objects": storage.delete_prefix(storage.project_prefix(project.organization_id, project.id))}
    map_ids = select(ProcessMap.id).where(ProcessMap.project_id == project.id).scalar_subquery()
    transcript_ids = select(Transcript.id).where(Transcript.project_id == project.id).scalar_subquery()
    for model, where in (
        (MapVersion, MapVersion.map_id.in_(map_ids)),
        (Conflict, Conflict.project_id == project.id),
        (ProcessMap, ProcessMap.project_id == project.id),
        (Job, Job.transcript_id.in_(transcript_ids)),
        (Transcript, Transcript.project_id == project.id),
    ):
        counts[model.__tablename__] = db.execute(delete(model).where(where)).rowcount  # type: ignore[attr-defined]
    db.delete(project)
    audit(db, "delete", "project", project.id, **counts)
    return counts


def purge_expired(now: datetime | None = None) -> int:
    """Retention: for projects with retention_days, delete each transcript's raw file and its
    text (segments) once it's older than that. Maps stay; their source quotes show as expired.
    Returns how many transcripts were purged."""
    now = now or datetime.now(UTC)
    purged = 0
    with system_session() as sys_db:
        projects = [
            (p.id, p.organization_id, p.retention_days)
            for p in sys_db.scalars(select(Project).where(Project.retention_days.is_not(None)))
        ]
    for project_id, org_id, days in projects:
        cutoff = now - timedelta(days=days or 0)
        with system_session() as db:
            bind(db, org_id)  # everything below is scoped to this project's org
            expired = db.scalars(
                select(Transcript).where(
                    Transcript.project_id == project_id,
                    Transcript.created_at < cutoff,
                    Transcript.content_expired_at.is_(None),
                )
            ).all()
            for t in expired:
                storage.delete(t.storage_key)
                t.segments, t.content_expired_at = None, now
                audit(db, "retention_purge", "transcript", t.id, retention_days=days)
            db.commit()
            purged += len(expired)
    if purged:
        log.info("retention: purged %d transcripts", purged)
    return purged
