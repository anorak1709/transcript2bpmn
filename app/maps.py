"""Map versioning. Every change (extraction, chat edit, visual save) is a new version; the
ProcessModel is canonical and the BPMN XML is regenerated from it each time."""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import MapVersion, ProcessMap
from app.models.process import ProcessModel
from app.pipeline.convert import KeptPositions
from app.pipeline.parse_bpmn import read_bpmn
from app.pipeline.run import model_to_bpmn


class NothingToUndo(Exception):
    pass


def create_map(
    db: Session, project_id: str, transcript_id: str | None, model: ProcessModel, source: str = "extract"
) -> ProcessMap:
    """transcript_id=None makes a project's merged map."""
    xml = model_to_bpmn(model)
    pmap = ProcessMap(
        project_id=project_id, transcript_id=transcript_id, model=model.model_dump(), bpmn_xml=xml, current_version=1
    )
    db.add(pmap)
    db.flush()
    db.add(MapVersion(map_id=pmap.id, version=1, source=source, model=pmap.model, bpmn_xml=xml))
    return pmap


def current_positions(pmap: ProcessMap) -> KeptPositions:
    """Where each node currently sits (after any manual moves), so regeneration keeps it there."""
    current = ProcessModel.model_validate(pmap.model)
    return read_bpmn(pmap.bpmn_xml.encode(), current)[1]


def commit_version(
    db: Session,
    pmap: ProcessMap,
    model: ProcessModel,
    source: str,
    keep: KeptPositions,
    ops: list[dict[str, Any]] | None = None,
    instruction: str | None = None,
) -> MapVersion:
    xml = model_to_bpmn(model, keep)  # raises before anything is written if the XML isn't valid
    db.execute(delete(MapVersion).where(MapVersion.map_id == pmap.id, MapVersion.version > pmap.current_version))
    version = MapVersion(
        map_id=pmap.id,
        version=pmap.current_version + 1,
        source=source,
        model=model.model_dump(),
        bpmn_xml=xml,
        ops=ops,
        instruction=instruction,
    )
    db.add(version)
    pmap.current_version, pmap.model, pmap.bpmn_xml = version.version, version.model, xml
    return version


def undo(db: Session, pmap: ProcessMap) -> None:
    if pmap.current_version <= 1:
        raise NothingToUndo
    prev = db.scalars(
        select(MapVersion).where(MapVersion.map_id == pmap.id, MapVersion.version == pmap.current_version - 1)
    ).one()
    pmap.current_version, pmap.model, pmap.bpmn_xml = prev.version, prev.model, prev.bpmn_xml


def versions(db: Session, map_id: str) -> list[MapVersion]:
    return list(db.scalars(select(MapVersion).where(MapVersion.map_id == map_id).order_by(MapVersion.version)))


class StaleVersion(Exception):
    """The caller edited an older version than the map's current one."""

    def __init__(self, current: int) -> None:
        super().__init__(f"current version is {current}")
        self.current = current


def parse_if_match(value: str | None) -> int | None:
    """`If-Match: "3"` (also W/"3" or bare 3) -> 3. None when the header is absent."""
    if value is None or value.strip() == "*":
        return None
    raw = value.strip().removeprefix("W/").strip('"')
    if not raw.isdigit():
        raise ValueError('If-Match must be a map version, e.g. "3"')
    return int(raw)


def lock_map(db: Session, map_id: str) -> ProcessMap | None:
    """Load a map with a row lock held until commit, re-read from the database (not the
    session cache), so concurrent edits of one map run one at a time and each sees the
    other's result."""
    return db.get(ProcessMap, map_id, with_for_update=True, populate_existing=True)


def check_version(pmap: ProcessMap, expected: int | None) -> None:
    if expected is not None and expected != pmap.current_version:
        raise StaleVersion(pmap.current_version)
