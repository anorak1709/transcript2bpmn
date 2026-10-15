from typing import Any

from arq import cron
from arq.connections import RedisSettings
from prometheus_client import start_http_server

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.workers.jobs import process_transcript, retention

setup_logging()


async def startup(ctx: dict[str, Any]) -> None:
    start_http_server(get_settings().metrics_port)  # Prometheus scrape target for job metrics


class WorkerSettings:
    functions = [process_transcript]
    cron_jobs = [cron(retention, hour=3, minute=0, run_at_startup=False)]  # daily retention purge
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    queue_name = get_settings().job_queue
    on_startup = startup
    job_timeout = 1800  # long transcripts + LLM latency
