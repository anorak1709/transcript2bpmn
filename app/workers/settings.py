from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.workers.jobs import process_transcript

setup_logging()


class WorkerSettings:
    functions = [process_transcript]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 1800  # long transcripts + LLM latency
