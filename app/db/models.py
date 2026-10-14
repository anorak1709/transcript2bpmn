import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    # Normalized segments (list of Segment dicts); filled by the pipeline. Source of truth for
    # the segment ids every map cites.
    segments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    # Audio only: False means speakers are all "Unknown speaker" and the UI should ask the
    # user to label them. None for text transcripts.
    diarization_available: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id"))
    # queued | transcribing (audio) | normalizing | extracting | converting | done | failed
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    map_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessMap(Base):
    __tablename__ = "maps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id"))
    # Current state, copied from map_versions[current_version] so reads are one row.
    model: Mapped[dict[str, Any]] = mapped_column(JSON)  # ProcessModel: canonical
    bpmn_xml: Mapped[str] = mapped_column(Text)  # always regenerated from model
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MapVersion(Base):
    """Linear edit history. Undo moves maps.current_version back; a new edit after an undo
    discards the undone versions (like any editor's undo stack)."""

    __tablename__ = "map_versions"
    __table_args__ = (UniqueConstraint("map_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    map_id: Mapped[str] = mapped_column(ForeignKey("maps.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))  # extract | chat | visual
    model: Mapped[dict[str, Any]] = mapped_column(JSON)
    bpmn_xml: Mapped[str] = mapped_column(Text)
    ops: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)  # chat: the applied patch ops
    instruction: Mapped[str | None] = mapped_column(Text)  # chat: what the user asked
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
