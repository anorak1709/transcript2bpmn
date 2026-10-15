# syntax=docker/dockerfile:1
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY pyproject.toml uv.lock ./
# Cache mount: dependency downloads survive between builds.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
# Chromium for diagram PNG/SVG export (bpmn-js in headless Chromium).
RUN playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
COPY . .
