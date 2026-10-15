# syntax=docker/dockerfile:1

# --- Web app (React + Vite): built to static files, served by FastAPI at /app -----------------
FROM node:24.20.0-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY web/ ./
RUN npm run build  # outDir ../app/static/app -> /src/app/static/app

# --- API + worker -------------------------------------------------------------------------------
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
COPY --from=web /src/app/static/app ./app/static/app
