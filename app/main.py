from fastapi import FastAPI

from app.api import health
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(title="transcript2bpmn")
app.include_router(health.router)
