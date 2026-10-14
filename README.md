# transcript2bpmn

Converts English meeting transcripts into BPMN 2.0 process maps (Camunda/Signavio-compatible).

**Core rule:** the LLM never writes BPMN XML. It extracts a typed `ProcessModel`
(`app/models/process.py`); deterministic code validates it and converts it to BPMN.

Status: **Phase 0** — skeleton, LLM provider, eval harness. Pipeline stages in
`app/pipeline/` are empty.

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker.

```bash
uv sync
cp .env.example .env        # set LLM_API_KEY and MODEL_* for live runs
make up                     # Postgres (host :5433), Redis, MinIO, API, worker
curl localhost:8000/health  # {"status":"ok"}
```

Or run the API locally against the compose services: `make run`.

| Command        | What it does                                   |
|----------------|------------------------------------------------|
| `make test`    | pytest                                         |
| `make lint`    | ruff check + format check + mypy (strict)      |
| `make fmt`     | auto-fix lint and format                       |
| `make eval`    | run the eval harness (stub pipeline by default)|
| `make migrate` | `alembic upgrade head`                         |
| `make worker`  | run the arq worker locally                     |

## Layout

```
app/api/        FastAPI routers
app/core/       settings (pydantic-settings), logging
app/llm/        LLMProvider interface + LiteLLM implementation
app/models/     ProcessModel schema
app/pipeline/   ingest, normalize, extract, validate, convert (Phase 1+)
app/db/         SQLAlchemy base + Alembic migrations
app/workers/    arq worker settings
eval/           gold cases, metrics, runner
```

## LLM provider

`LLMProvider.structured(prompt, input, schema, model_role)` returns a validated Pydantic
instance. The LiteLLM implementation calls the OpenAI **Responses API** with a strict
JSON Schema generated from the Pydantic model.

Everything is env config — no model names in code:

- `LLM_PROVIDER` — LiteLLM prefix (`openai`, `azure`, …)
- `LLM_API_BASE`, `LLM_API_KEY`, `LLM_API_VERSION` (Azure)
- `MODEL_EXTRACT`, `MODEL_FILTER`, `MODEL_REPAIR`, `MODEL_EDIT` — one per role
  (Azure: deployment names)

Model sent = `{LLM_PROVIDER}/{MODEL_<ROLE>}`. An unset role fails loudly.

**Tracing:** when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set, LiteLLM's
`langfuse_otel` callback logs every call (prompt, model, tokens, latency, cost).
Otherwise it's a no-op.

## Eval harness

Gold case = one folder in `eval/gold/`:

```
transcript.vtt | transcript.txt
expected.json   # hand-written ProcessModel
meta.yaml       # meeting_type: walkthrough | general; notes: ...
```

```bash
make eval                                                    # stub pipeline
make eval ARGS="--pipeline mymodule:fn --threshold 0.75"     # any Callable[[Path], ProcessModel]
```

Reports land in `eval/reports/<timestamp>.{md,json}` (gitignored) so runs can be diffed.

Metrics (macro-averaged over cases): task recall, task precision, lane accuracy, gateway
recall, flow-edge F1. Nodes are matched one-to-one within kind (task / gateway type /
event type) by fuzzy name similarity (`difflib`, threshold `--threshold`, default 0.8);
events match on type alone. Lane accuracy and edge F1 are computed through that matching,
so different ids in the prediction don't matter.

The default `eval.stub_pipeline` is an oracle (returns `expected.json`) — it proves the
plumbing, not quality. The 2 included cases are synthetic; add ≥10 real/permission-cleared
cases before Phase 1 is done.

## Notes

- Compose maps Postgres to host port **5433** to avoid clashing with a local Postgres.
- MinIO uses `cgr.dev/chainguard/minio` — `minio/minio` is no longer pullable from Docker Hub.
