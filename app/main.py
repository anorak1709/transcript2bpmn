from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

from app.api import health, keys, maps, projects, signoffs
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
app.include_router(signoffs.router)
app.include_router(signoffs.public)
app.include_router(metrics_router)
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


# --- Web app (web/, built by `make web-build` into app/static/app) ---------------------------
WEB = STATIC / "app"


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/app/")


@app.get("/editor/{map_id}", include_in_schema=False)
@app.get("/viewer/{map_id}", include_in_schema=False)  # older links keep working
def legacy_editor(map_id: str) -> RedirectResponse:
    return RedirectResponse(f"/app/maps/{map_id}", status_code=301)


@app.get("/settings", include_in_schema=False)
def legacy_settings() -> RedirectResponse:
    return RedirectResponse("/app/settings", status_code=301)


@app.get("/app", include_in_schema=False)
@app.get("/app/{path:path}", include_in_schema=False)
def web_app(path: str = "") -> Response:
    """Static build output; any other path is a client-side route, so it gets index.html."""
    if not (WEB / "index.html").exists():
        return PlainTextResponse("Web app not built. Run `make web-build`.", status_code=503)
    target = (WEB / path).resolve()
    if path and target.is_file() and target.is_relative_to(WEB.resolve()):
        # Hashed file names under assets/ never change content: cache them for a year.
        cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return FileResponse(target, headers={"Cache-Control": cache})
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
