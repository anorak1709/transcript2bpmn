from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import health, maps, projects
from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging()
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    app.state.arq = pool
    yield
    await pool.aclose()


app = FastAPI(title="transcript2bpmn", lifespan=lifespan)
app.include_router(health.router)
app.include_router(projects.router)
app.include_router(maps.router)


@app.get("/editor/{map_id}", include_in_schema=False)
@app.get("/viewer/{map_id}", include_in_schema=False)  # Phase 1 links keep working
def editor(map_id: str) -> FileResponse:
    return FileResponse(STATIC / "editor.html")
