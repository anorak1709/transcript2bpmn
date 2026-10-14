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

.PHONY: run worker up down migrate test lint fmt eval
