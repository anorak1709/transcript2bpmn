from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.workers.jobs import process_transcript, retention

setup_logging()


class WorkerSettings:
    functions = [process_transcript]
    cron_jobs = [cron(retention, hour=3, minute=0, run_at_startup=False)]  # daily retention purge
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 1800  # long transcripts + LLM latency
