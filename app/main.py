from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import health, keys, maps, projects
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.metrics import metrics_middleware, metrics_router

setup_logging()
STATIC = Path(__file__).parent / "static"

# Everything the editor loads is same-origin (bpmn-js is vendored), so the policy can forbid
# inline scripts and third-party code outright. Inline *styles* stay allowed: bpmn-js sets them.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    app.state.arq = pool
    app.state.redis = pool  # ArqRedis is a redis client too: rate-limit counters
    yield
    app.state.redis = None  # limiter treats a missing client as 'limits off'
    await pool.aclose()


app = FastAPI(title="transcript2bpmn", lifespan=lifespan)
app.include_router(health.router)
app.include_router(projects.router)
app.include_router(maps.router)
app.include_router(keys.router)
app.include_router(metrics_router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.middleware("http")(metrics_middleware)


@app.middleware("http")
async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("X-Frame-Options", "DENY")
    if h.get("content-type", "").startswith("text/html"):
        h.setdefault("Content-Security-Policy", CSP)
    if request.url.scheme == "https":  # behind the TLS proxy (uvicorn --proxy-headers)
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


# Off unless CORS_ORIGINS is set: the editor is same-origin and API clients aren't browsers.
if origins := get_settings().cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type"],
        max_age=600,
    )


@app.get("/editor/{map_id}", include_in_schema=False)
@app.get("/viewer/{map_id}", include_in_schema=False)  # Phase 1 links keep working
def editor(map_id: str) -> FileResponse:
    return FileResponse(STATIC / "editor.html")


@app.get("/settings", include_in_schema=False)
def settings_page() -> FileResponse:
    """API key management page (lists, creates, revokes keys for the caller's org)."""
    return FileResponse(STATIC / "settings.html")
