"""Sign-up and sign-in by email magic link, workspaces, invitations.

A magic link signs a person in: their first sign-in creates their own workspace; an invitation
link signs them into the inviting workspace. The browser then holds an expiring session key
(app/auth.py), so everything downstream (tenancy, rate limits, audit) is unchanged. API keys
remain for integrations.
"""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.auth import DB, CurrentPrincipal, create_org, create_session
from app.core.config import get_settings
from app.db.models import ApiKey, Invite, LoginToken, Membership, Organization, User
from app.db.tenancy import bind, system_session
from app.email import send
from app.ratelimit import ip_limit, rate_limit

public = APIRouter(prefix="/auth")
router = APIRouter(dependencies=[Depends(rate_limit("api"))])

# ponytail: a format check only; the real test of an address is the link arriving.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class EmailIn(BaseModel):
    email: str = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def _valid(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("Enter a valid email address")
        return v


def _send_link(db: Session, email: str, invite: Invite | None = None, org_name: str | None = None) -> None:
    s = get_settings()
    token = "ml_" + secrets.token_urlsafe(32)
    db.add(
        LoginToken(
            email=email, token_hash=_hash(token), invite_id=invite.id if invite else None,
            expires_at=datetime.now(UTC) + timedelta(minutes=s.magic_link_minutes),
        )
    )  # fmt: skip
    link = f"{s.public_url.rstrip('/')}/app/auth?token={token}"
    if invite:
        subject = f"You're invited to {org_name} on Transcript to BPMN"
        lead = f"You've been invited to the {org_name} workspace on Transcript to BPMN."
    else:
        subject = "Your sign-in link for Transcript to BPMN"
        lead = "Use this link to sign in to Transcript to BPMN."
    minutes = s.magic_link_minutes
    note = f"The link works once and expires in {minutes} minutes. Didn't ask for it? Ignore this email."
    text = f"{lead}\n\n{link}\n\n{note}"
    html = (
        f"<p>{lead}</p><p><a href='{link}'>Open Transcript to BPMN</a></p>"
        f"<p style='color:#666'>The link works once and expires in {minutes} minutes. "
        "Didn't ask for it? Ignore this email.</p>"
    )
    send(email, subject, text, html)


@public.post("/magic-link", status_code=202, dependencies=[Depends(ip_limit("magic-link", 5))])
def request_link(body: EmailIn) -> dict[str, str]:
    """Email a one-time sign-in link. The same answer whether or not the address has an
    account, so this can't be used to find out who uses the product."""
    with system_session() as db:
        _send_link(db, body.email)
        db.commit()
    return {"status": "sent"}


class VerifyIn(BaseModel):
    token: str = Field(max_length=200)


class SessionOut(BaseModel):
    key: str
    email: str
    workspace_id: str
    workspace_name: str


@public.post("/verify", dependencies=[Depends(ip_limit("verify", 20))])
def verify_link(body: VerifyIn) -> SessionOut:
    """Exchange a magic link for a browser session. First sign-in creates the person's own
    workspace; an invitation link adds them to the inviting one."""
    now = datetime.now(UTC)
    with system_session() as db:
        t = db.scalars(select(LoginToken).where(LoginToken.token_hash == _hash(body.token))).first()
        expires = None if t is None else t.expires_at if t.expires_at.tzinfo else t.expires_at.replace(tzinfo=UTC)
        if t is None or expires is None or t.used_at is not None or expires < now:
            raise HTTPException(401, "This sign-in link has expired or was already used. Request a new one.")
        t.used_at = now
        user = db.scalars(select(User).where(User.email == t.email)).first()
        if user is None:
            user = User(email=t.email)
            db.add(user)
            db.flush()
        org_id: str | None = None
        if t.invite_id:
            invite = db.get(Invite, t.invite_id)
            if invite is not None:
                org_id = invite.organization_id
                invite.accepted_at = invite.accepted_at or now
                if not db.scalars(
                    select(Membership).where(Membership.user_id == user.id, Membership.organization_id == org_id)
                ).first():
                    db.add(Membership(organization_id=org_id, user_id=user.id, role="member"))
        if org_id is None:
            first = db.scalars(
                select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
            ).first()
            if first is not None:
                org_id = first.organization_id
            else:  # a new person: their own workspace
                org = create_org(db, f"{t.email.split('@')[0]}'s workspace")
                db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
                org_id = org.id
        db.flush()
        key = create_session(db, org_id, user.id, user.email)
        name = db.get_one(Organization, org_id).name
        bind(db, org_id)
        audit(db, "sign_in", "user", user.id, via="invite" if t.invite_id else "magic_link")
        db.commit()
        return SessionOut(key=key, email=user.email, workspace_id=org_id, workspace_name=name)


class WorkspaceRef(BaseModel):
    id: str
    name: str
    role: str


class MeOut(BaseModel):
    email: str | None  # None: an integration's API key, not a person
    workspace: WorkspaceRef
    workspaces: list[WorkspaceRef]
    sandbox: bool


def _memberships(user_id: str) -> list[WorkspaceRef]:
    with system_session() as sys_db:
        rows = sys_db.execute(
            select(Membership, Organization)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at)
        ).all()
        return [WorkspaceRef(id=o.id, name=o.name, role=m.role) for m, o in rows]


@router.get("/auth/me")
def me(db: DB, who: CurrentPrincipal) -> MeOut:
    org = db.get_one(Organization, who.org_id)
    email = None
    workspaces: list[WorkspaceRef] = []
    role = "owner"  # an API key acts for the whole workspace
    if who.user_id:
        user = db.get_one(User, who.user_id)
        email = user.email
        workspaces = _memberships(user.id)
        role = next((w.role for w in workspaces if w.id == org.id), "member")
    return MeOut(
        email=email,
        workspace=WorkspaceRef(id=org.id, name=org.name, role=role),
        workspaces=workspaces,
        sandbox=org.sandbox_expires_at is not None,
    )


class SwitchIn(BaseModel):
    workspace_id: str


@router.post("/auth/switch")
def switch(body: SwitchIn, db: DB, who: CurrentPrincipal) -> SessionOut:
    """Move this browser to another workspace the person belongs to (a new session key)."""
    if not who.user_id or body.workspace_id not in {w.id for w in _memberships(who.user_id)}:
        raise HTTPException(404, "Workspace not found")
    with system_session() as sys_db:
        user = sys_db.get_one(User, who.user_id)
        sys_db.get_one(ApiKey, who.api_key_id).revoked_at = datetime.now(UTC)
        key = create_session(sys_db, body.workspace_id, user.id, user.email)
        name = sys_db.get_one(Organization, body.workspace_id).name
        sys_db.commit()
    return SessionOut(key=key, email=user.email, workspace_id=body.workspace_id, workspace_name=name)


@router.post("/auth/logout")
def logout(db: DB, who: CurrentPrincipal) -> dict[str, str]:
    """End this browser session. Integration API keys are revoked in Settings instead."""
    if who.user_id:
        db.get_one(ApiKey, who.api_key_id).revoked_at = datetime.now(UTC)
        db.commit()
    return {"status": "signed out"}


class MemberOut(BaseModel):
    email: str
    role: str
    joined_at: datetime | None


class InviteOut(BaseModel):
    id: str
    email: str
    created_at: datetime | None
    accepted_at: datetime | None


@router.get("/members")
def members(db: DB) -> list[MemberOut]:
    rows = db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id).order_by(Membership.created_at)
    )
    return [MemberOut(email=u.email, role=m.role, joined_at=m.created_at) for m, u in rows]


@router.get("/invites")
def list_invites(db: DB) -> list[InviteOut]:
    rows = db.scalars(select(Invite).where(Invite.accepted_at.is_(None)).order_by(Invite.created_at))
    return [InviteOut.model_validate(i, from_attributes=True) for i in rows]


@router.post("/invites", status_code=201)
def invite(body: EmailIn, db: DB, who: CurrentPrincipal) -> InviteOut:
    """Invite a colleague: they get a sign-in link that adds them to this workspace."""
    org = db.get_one(Organization, who.org_id)
    if org.sandbox_expires_at is not None:
        raise HTTPException(403, "Demo sandboxes can't invite people")
    inv = Invite(email=body.email, invited_by=who.user_id)
    db.add(inv)
    db.flush()
    _send_link(db, body.email, inv, org.name)
    audit(db, "invite", "invite", inv.id)
    db.commit()
    return InviteOut.model_validate(inv, from_attributes=True)


@router.delete("/invites/{invite_id}")
def cancel_invite(invite_id: str, db: DB) -> dict[str, str]:
    inv = db.get(Invite, invite_id)
    if inv is None or inv.accepted_at is not None:
        raise HTTPException(404, "Invitation not found")
    db.delete(inv)  # its link stops working: verify finds no invite and won't add the person
    audit(db, "cancel_invite", "invite", invite_id)
    db.commit()
    return {"status": "cancelled"}


# --- Public demo ----------------------------------------------------------------------------

demo = APIRouter(prefix="/demo")


class DemoStatus(BaseModel):
    sandboxes: bool  # "Try the demo" is offered
    demo_mode: bool  # this whole deployment has AI switched off
    sandbox_hours: int


@demo.get("/status")
def demo_status() -> DemoStatus:
    s = get_settings()
    return DemoStatus(sandboxes=s.demo_sandboxes, demo_mode=s.demo_mode, sandbox_hours=s.sandbox_hours)


@demo.post(
    "/sandbox",
    status_code=201,
    dependencies=[Depends(ip_limit("sandbox", 3)), Depends(ip_limit("sandbox-all", 20, per_ip=False))],
)
def new_sandbox() -> SessionOut:
    """One click, no sign-up: a fresh copy of the sample workspace for this visitor, with AI
    switched off, deleted after SANDBOX_HOURS."""
    from app.demo import create_sandbox

    if not get_settings().demo_sandboxes:
        raise HTTPException(404, "The demo isn't enabled on this server")
    org_id, key = create_sandbox()
    return SessionOut(key=key, email="", workspace_id=org_id, workspace_name="Demo sandbox")
