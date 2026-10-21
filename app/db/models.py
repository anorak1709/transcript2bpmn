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
    # Corrections flywheel (app/corrections.py): off | anonymised | full. Opt-in only.
    share_corrections: Mapped[str] = mapped_column(String(16), default="off", server_default="off")
    # Public demo sandboxes (app/demo.py) are deleted after this; never AI-processed.
    sandbox_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class User(Base):
    """A person who signs in by email (magic link). Not tenant-scoped: a user can belong to
    several workspaces through memberships."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-case
    created_at: Mapped[datetime] = _created()


class LoginToken(Base):
    """A one-time magic link (sha256 of the token stored). `invite_id` set when the link is an
    invitation into a workspace."""

    __tablename__ = "login_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invite_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Tenant:
    """Every row that belongs to a customer. app/db/tenancy.py filters all ORM queries on
    this column and stamps it on inserts, so no query can cross organizations."""

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)


class Membership(Tenant, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")  # owner | member
    created_at: Mapped[datetime] = _created()


class Invite(Tenant, Base):
    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320))
    invited_by: Mapped[str | None] = mapped_column(String(36))  # user id
    created_at: Mapped[datetime] = _created()
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(Tenant, Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(16), unique=True)  # public lookup part of the key
    key_hash: Mapped[str] = mapped_column(String(64))  # sha256 of the full key; the key itself is never stored
    # Set for browser sessions from a magic link: whose session it is, and when it lapses.
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    # {speaker name: "owner" | "performer" | "observer"}, set by the user (app/insights.py)
    speaker_roles: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    # Gaps the user said aren't gaps (ids from app/pipeline/gaps.py), so they stop coming back
    dismissed_gaps: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[datetime] = _created()


class Transcript(Tenant, Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    # meeting: merged into the project map. policy: an SOP/policy document, only compared
    # against the map (app/policy.py), never merged into it.
    purpose: Mapped[str] = mapped_column(String(16), default="meeting", server_default="meeting")
    storage_key: Mapped[str] = mapped_column(String(512))
    # Normalized segments (list of Segment dicts); filled by the pipeline. Source of truth for
    # the segment ids every map cites.
    segments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    # Audio only: False means speakers are all "Unknown speaker" and the UI should ask the
    # user to label them. None for text transcripts.
    diarization_available: Mapped[bool | None] = mapped_column(Boolean)
    # Live interviews (app/live.py): "recording" while chunks arrive, "finished" once merged.
    live_status: Mapped[str | None] = mapped_column(String(16))
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
    # Review queue: steps a person has checked (node ids), so they drop out of the queue.
    reviewed_node_ids: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
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
    # owner | order | condition | sequence; policy only: missing_step | unofficial_step
    kind: Mapped[str] = mapped_column(String(16))
    # meeting: meetings disagree with each other (also an open question on the map).
    # policy: the map (what people said) differs from a policy document; listed separately.
    origin: Mapped[str] = mapped_column(String(16), default="meeting", server_default="meeting")
    description: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSON)
    # [{transcript_id, segment_ids, says}] per side of the disagreement
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    node_ids: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved
    resolution: Mapped[str | None] = mapped_column(Text)  # the option applied; None = fixed by hand
    created_at: Mapped[datetime] = _created()


class Signoff(Tenant, Base):
    """A stakeholder's review link for their part of the merged map. The token is shown once;
    only its sha256 is stored, like API keys."""

    __tablename__ = "signoffs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))  # who is asked
    lane_ids: Mapped[list[str]] = mapped_column(JSON)  # their part of the map
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    requested_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str | None] = mapped_column(String(32))  # approved | changes_requested
    comment: Mapped[str | None] = mapped_column(Text)
    decided_version: Mapped[int | None] = mapped_column(Integer)  # the map version they saw
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Correction(Tenant, Base):
    """A person fixing something the AI extracted: a free label for where it was wrong.
    Recorded for every human edit (visual saves, chat edits); shared for test cases only if
    the workspace opted in (Organization.share_corrections)."""

    __tablename__ = "corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    map_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)  # the version the fix produced
    via: Mapped[str] = mapped_column(String(16))  # visual | chat
    kind: Mapped[str] = mapped_column(String(16))  # rename | move | retype | delete | add | connect | disconnect
    node_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    segment_ids: Mapped[list[str]] = mapped_column(JSON, default=list)  # the evidence the AI used
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
