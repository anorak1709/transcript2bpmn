run:
	uv run uvicorn app.main:app --reload

worker:
	uv run arq app.workers.settings.WorkerSettings

up:
	docker compose up -d --build

down:
	docker compose down

migrate:
	uv run alembic upgrade head

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy app eval tests

fmt:
	uv run ruff check --fix .
	uv run ruff format .

eval:
	uv run python -m eval.run_eval $(ARGS)

.PHONY: run worker up down migrate test lint fmt eval backup restore web-install web-dev web-build web-check

backup:
	scripts/backup.sh $(DIR)

restore:
	scripts/restore.sh $(DIR) $(DB) $(BUCKET)

web-install:
	cd web && npm ci

web-dev:  # http://localhost:5173/app/ (proxies the API to :8000; run `make run` too)
	cd web && npm run dev

web-build:
	cd web && npm run build

web-check:
	cd web && npm run typecheck && npm run lint && npm run format:check
