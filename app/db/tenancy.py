"""Tenant isolation, enforced once at the session level instead of in every query.

- Every ORM statement (select, Session.get, lazy load, bulk update/delete) in a tenant session
  gets `organization_id = <org>` added for every Tenant table, automatically.
- New Tenant rows get the session's organization stamped on flush; a row for another org is refused.
- A session with neither an org nor an explicit `system` flag refuses to run ORM statements at
  all (fail closed), so forgetting to scope a session is an error, not a data leak.

System sessions (auth lookup, worker bootstrap, retention) are explicit and greppable.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.db.base import SessionLocal
from app.db.models import Organization, Tenant


class TenancyError(RuntimeError):
    pass


@event.listens_for(Session, "do_orm_execute")
def _scope_statements(state: ORMExecuteState) -> None:
    info = state.session.info
    if info.get("system"):
        return
    org = info.get("org_id")
    if org is None:
        raise TenancyError("ORM query on a session without an organization (use tenant_session/system_session)")
    state.statement = state.statement.options(
        with_loader_criteria(Tenant, lambda cls: cls.organization_id == org, include_aliases=True)
    )


@event.listens_for(Session, "before_flush")
def _stamp_inserts(session: Session, *_: object) -> None:
    org = session.info.get("org_id")
    for obj in session.new:
        if isinstance(obj, Organization) or not isinstance(obj, Tenant):
            continue
        if org is None:
            if not session.info.get("system") or obj.organization_id is None:
                raise TenancyError(f"Refusing to insert {type(obj).__name__} without an organization")
        elif obj.organization_id is None:
            obj.organization_id = org
        elif obj.organization_id != org:
            raise TenancyError(f"Refusing to insert {type(obj).__name__} for another organization")


def bind(session: Session, org_id: str) -> Session:
    session.info.update(org_id=org_id, system=False)
    return session


@contextmanager
def tenant_session(org_id: str) -> Iterator[Session]:
    with SessionLocal() as db:
        yield bind(db, org_id)


@contextmanager
def system_session() -> Iterator[Session]:
    """Unscoped. Only for auth, job bootstrap and retention; never hand one to request code."""
    with SessionLocal() as db:
        db.info["system"] = True
        yield db
