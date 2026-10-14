from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings


async def ping(ctx: dict[str, Any]) -> str:
    # ponytail: arq refuses to start with zero functions; real jobs arrive in Phase 1.
    return "pong"


class WorkerSettings:
    functions = [ping]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
