"""API-key auth, one or more keys per organization.

Key format: `t2b_<prefix>_<secret>`. Only the sha256 of the whole key is stored; the prefix
is a public lookup handle so verification is one indexed row plus a constant-time compare.
Send it as `Authorization: Bearer <key>` or `X-API-Key: <key>`.
"""

import hashlib
import hmac
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.db.models import ApiKey, Organization
from app.db.tenancy import bind, system_session


@dataclass(frozen=True)
class Principal:
    org_id: str
    api_key_id: str


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_org(db: Session, name: str) -> Organization:
    org = Organization(name=name)
    db.add(org)
    db.flush()
    return org


def create_key(db: Session, org_id: str, name: str = "default") -> str:
    """Returns the full key. It's shown once and can't be recovered later."""
    prefix = secrets.token_hex(4)
    key = f"t2b_{prefix}_{secrets.token_urlsafe(32)}"
    db.add(ApiKey(organization_id=org_id, name=name, prefix=prefix, key_hash=_hash(key)))
    db.flush()
    return key


def verify(key: str) -> Principal | None:
    parts = key.split("_")
    if len(parts) < 3 or parts[0] != "t2b":
        return None
    with system_session() as db:
        row = db.scalars(select(ApiKey).where(ApiKey.prefix == parts[1], ApiKey.revoked_at.is_(None))).first()
    if row is None or not hmac.compare_digest(row.key_hash, _hash(key)):
        return None
    return Principal(org_id=row.organization_id, api_key_id=row.id)


def principal(request: Request) -> Principal:
    auth = request.headers.get("authorization", "")
    key = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else request.headers.get("x-api-key", "")
    found = verify(key) if key else None
    if found is None:
        raise HTTPException(401, "Missing or invalid API key", headers={"WWW-Authenticate": "Bearer"})
    return found


CurrentPrincipal = Annotated[Principal, Depends(principal)]


def get_db(who: CurrentPrincipal) -> Iterator[Session]:
    """Request DB session, scoped to the caller's organization (see app/db/tenancy.py)."""
    with SessionLocal() as db:
        db.info["api_key_id"] = who.api_key_id
        yield bind(db, who.org_id)


DB = Annotated[Session, Depends(get_db)]
