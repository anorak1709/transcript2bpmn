"""Prometheus metrics: HTTP traffic, pipeline jobs, LLM calls, exports.

API process: GET /metrics (needs `Authorization: Bearer $METRICS_TOKEN`; disabled when unset).
Worker process: its own exporter on METRICS_PORT (default 9100), started by the arq worker.
"""

import hmac
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.core.config import get_settings

HTTP_REQUESTS = Counter("t2b_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("t2b_http_request_seconds", "HTTP request latency", ["method", "route"])
JOBS = Counter("t2b_jobs_total", "Pipeline jobs finished", ["status"])
JOB_STAGE = Histogram(
    "t2b_job_stage_seconds", "Time per pipeline stage", ["stage"], buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 900)
)
LLM_CALLS = Counter("t2b_llm_calls_total", "LLM / embedding calls", ["role", "outcome"])
LLM_LATENCY = Histogram("t2b_llm_call_seconds", "LLM / embedding call latency", ["role"])
EXPORTS = Counter("t2b_exports_total", "Map exports", ["format"])


@contextmanager
def timed_llm_call(role: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    except Exception:
        LLM_CALLS.labels(role, "error").inc()
        raise
    else:
        LLM_CALLS.labels(role, "ok").inc()
    finally:
        LLM_LATENCY.labels(role).observe(time.perf_counter() - start)


async def metrics_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    # The route *template* (/maps/{map_id}), never the raw path: ids would explode cardinality.
    route = getattr(request.scope.get("route"), "path", "unmatched")
    HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    HTTP_LATENCY.labels(request.method, route).observe(time.perf_counter() - start)
    return response


metrics_router = APIRouter()


@metrics_router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    token = get_settings().metrics_token
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(given, token):
        raise HTTPException(404)  # disabled or wrong token: don't advertise the endpoint
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
