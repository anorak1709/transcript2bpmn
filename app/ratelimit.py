"""Per-API-key rate limits (fixed one-minute windows in Redis) and monthly processing quotas.

Two buckets: "api" (every authenticated call) and "heavy" (calls that cost LLM/ASR money or
real CPU: upload, process, chat, image export). 0 disables a limit.
"""

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import CurrentPrincipal
from app.core.config import get_settings
from app.db.models import Job, Organization

WINDOW_S = 60


def rate_limit(bucket: str) -> Callable[[Request, CurrentPrincipal], Awaitable[None]]:
    async def check(request: Request, who: CurrentPrincipal) -> None:
        s = get_settings()
        limit = s.rate_limit_heavy_per_minute if bucket == "heavy" else s.rate_limit_per_minute
        redis = getattr(request.app.state, "redis", None)  # set in the app lifespan
        if not limit or redis is None:
            return
        window = int(time.time() // WINDOW_S)
        key = f"rl:{bucket}:{who.api_key_id}:{window}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, WINDOW_S * 2)
        if count > limit:
            retry = WINDOW_S - int(time.time()) % WINDOW_S
            raise HTTPException(
                429, f"Rate limit: {limit} {bucket} requests per minute", headers={"Retry-After": str(retry)}
            )

    return check


def ip_limit(bucket: str, per_minute: int) -> Callable[[Request], Awaitable[None]]:
    """Per client IP, for public endpoints that have no API key to count against (sign-up, demo)."""

    async def check(request: Request) -> None:
        redis = getattr(request.app.state, "redis", None)
        if not per_minute or redis is None:
            return
        ip = request.headers.get("fly-client-ip") or (request.client.host if request.client else "?")
        key = f"rl:ip:{bucket}:{ip}:{int(time.time() // WINDOW_S)}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, WINDOW_S * 2)
        if count > per_minute:
            raise HTTPException(429, "Too many requests. Try again in a minute.", headers={"Retry-After": "60"})

    return check


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def jobs_this_month(db: Session) -> int:
    """Processing jobs started by the caller's organization this calendar month (UTC)."""
    return db.scalar(select(func.count(Job.id)).where(Job.created_at >= month_start())) or 0


def check_quota(db: Session, org_id: str) -> None:
    quota = db.get_one(Organization, org_id).monthly_jobs_quota
    if quota is not None and jobs_this_month(db) >= quota:
        raise HTTPException(429, f"Monthly processing quota of {quota} transcripts reached")
