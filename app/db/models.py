import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Organization(Base):
    """A customer. Not tenant-scoped itself: only reachable through auth / system sessions."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    # Transcripts this org may process per calendar month (UTC). None = unlimited.
    monthly_jobs_quota: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()


class Tenant:
    """Every row that belongs to a customer. app/db/tenancy.py filters all ORM queries on
    this column and stamps it on inserts, so no query can cross organizations."""

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)


class ApiKey(Tenant, Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(16), unique=True)  # public lookup part of the key
    key_hash: Mapped[str] = mapped_column(String(64))  # sha256 of the full key; the key itself is never stored
    created_at: Mapped[datetime] = _created()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Project(Tenant, Base):
    """Groups transcripts describing the same process; owns the merged map."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    # Raw files + transcript text are purged this many days after upload. None = keep.
    retention_days: Mapped[int | None] = mapped_column(Integer)
    merged_map_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = _created()


class Transcript(Tenant, Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    # Normalized segments (list of Segment dicts); filled by the pipeline. Source of truth for
    # the segment ids every map cites.
    segments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    # Audio only: False means speakers are all "Unknown speaker" and the UI should ask the
    # user to label them. None for text transcripts.
    diarization_available: Mapped[bool | None] = mapped_column(Boolean)
    # Set when retention purged the raw file and segments. Maps still work; quotes don't.
    content_expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Job(Tenant, Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id"))
    # queued | transcribing (audio) | normalizing | extracting | converting | merging | done | failed
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    map_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessMap(Tenant, Base):
    """Either one transcript's extraction (transcript_id set) or a project's merged map
    (transcript_id null, citations qualified as `<transcript_id>:<segment_id>`)."""

    __tablename__ = "maps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    transcript_id: Mapped[str | None] = mapped_column(ForeignKey("transcripts.id"))
    # Current state, copied from map_versions[current_version] so reads are one row.
    model: Mapped[dict[str, Any]] = mapped_column(JSON)  # ProcessModel: canonical
    bpmn_xml: Mapped[str] = mapped_column(Text)  # always regenerated from model
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = _created()


class MapVersion(Tenant, Base):
    """Linear edit history. Undo moves maps.current_version back; a new edit after an undo
    discards the undone versions (like any editor's undo stack)."""

    __tablename__ = "map_versions"
    __table_args__ = (UniqueConstraint("map_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    map_id: Mapped[str] = mapped_column(ForeignKey("maps.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))  # extract | chat | visual | merge
    model: Mapped[dict[str, Any]] = mapped_column(JSON)
    bpmn_xml: Mapped[str] = mapped_column(Text)
    ops: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)  # chat/merge: the applied patch ops
    instruction: Mapped[str | None] = mapped_column(Text)  # chat: what the user asked
    created_at: Mapped[datetime] = _created()


class Conflict(Tenant, Base):
    """Transcripts that disagree. Never resolved silently: each one is also an OpenQuestion
    (id `conflict_<id>`) on the merged map until the user resolves it."""

    __tablename__ = "conflicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # owner | order | condition | sequence
    description: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSON)
    # [{transcript_id, segment_ids, says}] per side of the disagreement
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    node_ids: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved
    resolution: Mapped[str | None] = mapped_column(Text)  # the option applied; None = fixed by hand
    created_at: Mapped[datetime] = _created()


class AuditLog(Tenant, Base):
    """Who did what. Metadata only (ids, counts, action names): never meeting content, so it
    can outlive the data it describes (e.g. survives project deletion)."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    api_key_id: Mapped[str | None] = mapped_column(String(36))  # None = system (retention, worker)
    action: Mapped[str] = mapped_column(String(32), index=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(36))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()
