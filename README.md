# transcript2bpmn

Converts English meeting transcripts into BPMN 2.0 process maps (Camunda/Signavio-compatible).

**Core rule:** the LLM never writes BPMN XML. It extracts a typed `ProcessModel`
(`app/models/process.py`); deterministic code validates it and converts it to BPMN.

Status: **Phase 2**: text transcripts (.vtt/.srt/.txt/.docx) and audio recordings
(.mp3/.m4a/.wav/.webm/.mp4) → BPMN XML, rendered in a read-only viewer. Not yet built:
validation/repair and editing (Phase 3), multi-meeting merge (Phase 4).

## Pipeline

```
upload ─► ingest ─► normalize ─► extract (filter pass, extract pass) ─► convert ─► XSD check
          parse     fillers,     LLM "filter" role  LLM "extract" role   lxml +
          file      merge,       drops chatter      → ProcessModel       layout
                    ids s1..sN
```

- **Ingest** (`app/pipeline/ingest.py`): webvtt-py for VTT/SRT (`<v Name>` voice tags or
  `Name:` prefixes), python-docx for DOCX, `Speaker: text` detection for TXT/DOCX lines.
  Unparseable uploads are rejected with 400 at upload time.
- **Normalize** (`normalize.py`): deterministic filler stripping (um/uh/erm/hmm, "you know"
  only when set off by commas), merge consecutive same-speaker fragments, assign `s1..sN`.
  Those ids are stored on the transcript and every node cites them. No LLM cleanup pass yet;
  add one if eval shows the rules aren't enough.
- **Extract** (`extract.py`): prompts are versioned files in `app/pipeline/prompts/`
  (`filter_v1.md`, `extract_v1.md`). To change a prompt, add `_v2` and bump the constant, so
  eval reports stay comparable. Invented citation ids are dropped; a node left uncited
  borrows its neighbours' citations with confidence halved, so every node cites ≥1 real segment.
- **Transcribe** (`app/pipeline/transcribe/`, audio only): see *Audio* below.
- **Convert** (`convert.py`): see *Layout* below. Output is validated against the official
  OMG BPMN 2.0 XSD (`app/pipeline/xsd/`) before it is stored.

## API

| Endpoint | |
|---|---|
| `POST /transcripts` (multipart `file`) | upload; stores raw file in S3/MinIO + row in Postgres |
| `POST /transcripts/{id}/process` | enqueue the pipeline (arq); returns the job |
| `GET /jobs/{id}` | `queued → (transcribing) → normalizing → extracting → converting → done \| failed` (+ `error`, `map_id`) |
| `GET /maps/{id}` | `{model, bpmn_xml}`. The model is canonical; the XML is derived from it |
| `GET /viewer/{map_id}` | read-only bpmn-js viewer + `.bpmn` download |

```bash
curl -F file=@eval/gold/01_invoice_approval/transcript.vtt localhost:8000/transcripts
curl -X POST localhost:8000/transcripts/<id>/process
curl localhost:8000/jobs/<job_id>          # until status=done
open http://localhost:8000/viewer/<map_id>
```

## Audio

Platform transcript exports (Teams/Zoom/Meet VTT) stay the primary input. Audio is the
fallback when no export exists. Requires ffmpeg (`brew install ffmpeg`; it's in the Docker image).

- Upload audio to the same `POST /transcripts`. It's checked with ffprobe and streamed to
  object storage (up to 1 GB). The job gets an extra `transcribing` stage.
- `Transcriber` interface (`transcribe/base.py`): `transcribe(audio_path) -> Transcription`
  (segments in the normalizer's schema + `diarization_available`). Pick the adapter with
  `TRANSCRIBE_PROVIDER`.
- **OpenAI adapter** (`transcribe/openai.py`), model from `TRANSCRIBE_MODEL`:
  - Audio is re-encoded to 16 kHz mono MP3 and split into `TRANSCRIBE_CHUNK_SECONDS` chunks
    (default 600 s ≈ 3.6 MB, far under the 25 MB API limit). Chunk offsets are measured, and
    `stitch()` shifts timestamps onto the recording timeline, keeping them monotonic and in bounds.
  - Diarization: models whose name contains `diarize` are called with `diarized_json`.
    Speaker labels restart at "A" on every request, so after chunk 1 the adapter sends 2–10 s
    voice clips of up to 4 speakers as `known_speaker_references`. Later chunks then reuse
    the same labels. A voice not among the references stays distinct (`Speaker C (part 3)`)
    rather than being guessed.
  - Other models: `whisper*` → timed segments; anything else → text split into sentences
    with approximate timestamps. All speakers are `Unknown speaker`, and
    `transcripts.diarization_available = false` so the UI can ask the user to label speakers.
    Unknown-speaker segments are never merged.
- **Second provider:** `transcribe/deepgram.py` is a documented stub with the steps to add one.

### ASR benchmark

```bash
# synthetic multi-voice recording + reference (macOS `say`)
uv run python -m eval.asr.make_sample eval/gold/01_invoice_approval/transcript.vtt --minutes 32 --out eval/asr/local/long
# WER + speaker-attribution accuracy per provider[:model]
uv run python -m eval.asr_benchmark eval/asr/samples --configs openai:<model-a> openai:<model-b>
```

`eval/asr/samples/` has a 1-minute two-speaker sample. Put long or real recordings in
`eval/asr/local/` (gitignored). Each audio file needs a `<stem>.ref.txt` with `Speaker: text` lines.
Speaker accuracy maps each hypothesis label to the reference speaker it overlaps most,
then counts correctly attributed aligned words.

## Layout

**bpmn-auto-layout was evaluated and not used.** Its own README says it only lays out the
first participant of a collaboration, and its source only gives lanes a default size. It
never places nodes inside their lane, so every lane assignment would be lost visually.

Instead, `convert.layout()` is a small lane-aware layout in Python:
- x: longest-path layering over the flow graph (DFS marks loop-back flows and ignores them
  for layering; they're drawn underneath)
- y: lane band, in the model's lane order; nodes of one lane that share a column get sub-rows
- orthogonal edge routing, fixed spacing

Nodes referencing an unknown lane go to an "Unassigned" lane, and dangling flows are dropped.
Real validation is Phase 3.

## Manual Camunda Modeler check

The XSD check is automated (`tests/test_convert.py`, `tests/test_integration.py`). Camunda
Modeler is a manual check per release:

1. Process a transcript, open `/viewer/<map_id>`, click **Download .bpmn**.
2. Open it in [Camunda Modeler](https://camunda.com/download/modeler/) (File → Open).
3. Pass if it opens with no import warnings, lanes contain their tasks, and gateway
   condition labels show.

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker, ffmpeg (audio only).

```bash
uv sync
cp .env.example .env        # set LLM_API_KEY and MODEL_* for live runs
make up                     # Postgres (host :5433), Redis, MinIO, API, worker
curl localhost:8000/health  # {"status":"ok"}
```

Or run the API + worker locally against the compose services:
`docker compose up -d postgres redis minio && make migrate && make run` (and `make worker`
in another shell).

Tests: `tests/test_integration.py` needs the compose services up and migrated; it skips
otherwise. Every other test is self-contained.

| Command        | What it does                                   |
|----------------|------------------------------------------------|
| `make test`    | pytest                                         |
| `make lint`    | ruff check + format check + mypy (strict)      |
| `make fmt`     | auto-fix lint and format                       |
| `make eval`    | run the eval harness (real pipeline by default)|
| `make migrate` | `alembic upgrade head`                         |
| `make worker`  | run the arq worker locally                     |

## Repo layout

```
app/api/        FastAPI routers
app/core/       settings (pydantic-settings), logging
app/llm/        LLMProvider interface + LiteLLM implementation
app/models/     ProcessModel schema
app/pipeline/   ingest, transcribe/, normalize, extract, convert, run (validate: Phase 3)
app/static/     viewer.html
app/storage.py  S3/MinIO put/get
app/db/         SQLAlchemy base + Alembic migrations
app/workers/    arq worker settings
eval/           gold cases, metrics, runner; asr_benchmark.py + asr/ (audio samples)
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
make eval                                                    # real pipeline (needs .env LLM config)
make eval ARGS="--pipeline eval.stub_pipeline:pipeline"      # oracle stub, no LLM
make eval ARGS="--pipeline mymodule:fn --threshold 0.75"     # any Callable[[Path], ProcessModel]
```

Reports land in `eval/reports/<timestamp>.{md,json}` (gitignored) so runs can be diffed.

Metrics (macro-averaged over cases): task recall, task precision, lane accuracy, gateway
recall, flow-edge F1. Nodes are matched one-to-one within kind (task / gateway type /
event type) by fuzzy name similarity (`difflib`, threshold `--threshold`, default 0.8);
events match on type alone. Lane accuracy and edge F1 are computed through that matching,
so different ids in the prediction don't matter.

The default is the real pipeline (`app.pipeline.run:eval_pipeline`). If a case fails (e.g.
no API key), its traceback goes in the report and the run continues.
`eval.stub_pipeline` is an oracle (returns `expected.json`) — it proves the
plumbing, not quality. The 2 included cases are synthetic; add ≥10 real/permission-cleared
cases before Phase 1 is done.

## Notes

- Compose maps Postgres to host port **5433** to avoid clashing with a local Postgres.
- MinIO uses `cgr.dev/chainguard/minio` — `minio/minio` is no longer pullable from Docker Hub.
