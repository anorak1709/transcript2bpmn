"""API key management for the caller's own organization (the /settings page uses this)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit import audit
from app.auth import DB, CurrentPrincipal, create_key
from app.db.models import ApiKey
from app.ratelimit import rate_limit

router = APIRouter(prefix="/keys", dependencies=[Depends(rate_limit("api"))])


class KeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    revoked_at: datetime | None
    current: bool  # the key making this request


class NewKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class NewKeyOut(KeyOut):
    key: str  # shown once; only its hash is stored


def _out(k: ApiKey, who: CurrentPrincipal) -> KeyOut:
    return KeyOut(
        id=k.id,
        name=k.name,
        prefix=k.prefix,
        created_at=k.created_at,
        revoked_at=k.revoked_at,
        current=k.id == who.api_key_id,
    )


@router.get("")
def list_keys(db: DB, who: CurrentPrincipal) -> list[KeyOut]:
    return [_out(k, who) for k in db.scalars(select(ApiKey).order_by(ApiKey.created_at))]


@router.post("", status_code=201)
def new_key(body: NewKeyIn, db: DB, who: CurrentPrincipal) -> NewKeyOut:
    key = create_key(db, who.org_id, body.name)
    row = db.scalars(select(ApiKey).where(ApiKey.prefix == key.split("_")[1])).one()
    audit(db, "create_key", "api_key", row.id, name=body.name, prefix=row.prefix)
    db.commit()
    return NewKeyOut(**_out(row, who).model_dump(), key=key)


@router.delete("/{key_id}")
def revoke_key(key_id: str, db: DB, who: CurrentPrincipal) -> KeyOut:
    k = db.get(ApiKey, key_id)
    if k is None:
        raise HTTPException(404, "Key not found")
    if k.revoked_at is None:
        active = db.scalars(select(ApiKey.id).where(ApiKey.revoked_at.is_(None))).all()
        if active == [k.id]:
            raise HTTPException(409, "Can't revoke the organization's last active key; create another first")
        k.revoked_at = datetime.now(UTC)
        audit(db, "revoke_key", "api_key", k.id, prefix=k.prefix)
        db.commit()
    return _out(k, who)
