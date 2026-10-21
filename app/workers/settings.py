from typing import Any

from arq import cron
from arq.connections import RedisSettings
from prometheus_client import start_http_server

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.workers.jobs import live_chunk, process_transcript, purge_demo_sandboxes, retention

setup_logging()


async def startup(ctx: dict[str, Any]) -> None:
    start_http_server(get_settings().metrics_port)  # Prometheus scrape target for job metrics


class WorkerSettings:
    functions: list[Any] = [process_transcript, live_chunk]  # arq coroutines (signatures differ)
    cron_jobs = [
        cron(retention, hour=3, minute=0, run_at_startup=False),  # daily retention purge
        cron(purge_demo_sandboxes, minute=15, run_at_startup=False),  # hourly: expired demo sandboxes
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    queue_name = get_settings().job_queue
    on_startup = startup
    job_timeout = 1800  # long transcripts + LLM latency
