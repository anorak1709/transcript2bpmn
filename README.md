# transcript2bpmn

Converts English meeting transcripts into BPMN 2.0 process maps (Camunda/Signavio-compatible).

**Core rule:** the LLM never writes BPMN XML. It extracts a typed `ProcessModel`
(`app/models/process.py`); deterministic code validates it and converts it to BPMN.

Status: **Phase 4**: multi-tenant API (orgs + API keys) with projects that merge several
meetings into one map, conflict detection, retention, project deletion, an audit log, and
exports (BPMN, SVG/PNG, SOP). Out of scope: billing, SSO/SAML, self-hosted models.

## Pipeline

```
upload ─► ingest ─► normalize ─► extract (filter, extract) ─► validate/repair ─► convert ─► XSD check
          parse     fillers,     LLM "filter" + "extract"     graph checks;       lxml +
          file      merge,       → ProcessModel               LLM "repair" ≤2x    layout
                    ids s1..sN
```

- **Ingest** (`app/pipeline/ingest.py`): webvtt-py for VTT/SRT (`<v Name>` voice tags or
  `Name:` prefixes), python-docx for DOCX, `Speaker: text` detection for TXT/DOCX lines.
  Unparseable uploads are rejected with 400 at upload time.
- **Normalize** (`normalize.py`): deterministic filler stripping (um/uh/erm/hmm, "you know"
  only when set off by commas), merge consecutive same-speaker fragments, assign `s1..sN`.
  Those ids are stored on the transcript and every node cites them. Optional model pass
  (`NORMALIZE_LLM_CLEANUP=true`, "filter" role, `prompts/cleanup_v1.md`) fixes ASR
  misrecognitions and false starts per segment. Ids never change, and rewrites that are empty
  or much longer than the original are rejected.
- **Extract** (`extract.py`): prompts are versioned files in `app/pipeline/prompts/`
  (`filter_v1.md`, `extract_v2.md`). To change a prompt, add `_v2` and bump the constant, so
  eval reports stay comparable. Invented citation ids are dropped; a node left uncited
  borrows its neighbours' citations with confidence halved, so every node cites ≥1 real segment.
  **Long meetings:** above `EXTRACT_MAX_CHARS` (60k chars ≈ 15k tokens) the transcript is
  extracted in windows that overlap by 3 segments. The partial models are folded together
  with the multi-meeting merge, so a step seen in two windows is matched, not duplicated.
- **Transcribe** (`app/pipeline/transcribe/`, audio only): see *Audio* below.
- **Validate/repair** (`validate.py`): deterministic checks, each returning
  `{code, message, node_ids}`: `DUPLICATE_ID`, `INVALID_LANE`, `DANGLING_FLOW`,
  `NO_START_EVENT`, `MULTIPLE_START_EVENTS` (one per lane is allowed), `NO_END_EVENT`,
  `ORPHAN_NODE`, `UNREACHABLE`, `DEAD_END`, `GATEWAY_NO_BRANCH`, `MISSING_CONDITION`.
  On errors, the model, the errors and the source segments of the affected nodes go to the
  LLM ("repair" role, `prompts/repair_v1.md`), up to 2 attempts. The version with the fewest
  errors wins, and anything still wrong becomes an OpenQuestion ("Needs review (CODE): …").
  It never fails the job. Repair calls carry `repair_attempt` + `error_codes` as Langfuse
  metadata, and the eval report gets *repair attempts* / *unresolved errors* columns.
- **Convert** (`convert.py`): see *Layout* below. Output is validated against the official
  OMG BPMN 2.0 XSD (`app/pipeline/xsd/`) before it is stored.

## Web app

`web/`: React 19 + TypeScript, [shadcn/ui](https://ui.shadcn.com) (Radix primitives) +
Tailwind 4, TanStack Query, React Router, bpmn-js. `make web-build` builds it into
`app/static/app`, and FastAPI serves it at **`/app`**, same-origin, so the strict CSP holds
(no inline script, nothing loaded from a CDN). The Docker image builds it in a Node stage.

| Page | What it does |
|---|---|
| Sign in | paste an API key; it's checked before it's stored (this browser only) |
| Projects | all projects, map status and open disagreements; create a project (optional retention) |
| Project | drag-and-drop upload (text or audio; processing starts automatically), meetings table with **live job status** (polls while anything is running; failures show the error), disagreements with one button per option, export menu, delete (type the name to confirm) |
| Map editor | bpmn-js Modeler; side panel tabs: **Step** (transcript quotes with speaker and time, "added by you", low-confidence badge), **Questions** (conflicts with option buttons; click to jump to the step), **Issues** (validation); chat edits; undo, version history, export, save; warns before leaving with unsaved changes |
| Settings | API keys (create, shown once; revoke), monthly usage and rate limits, recent activity (audit log) |

Light, dark and system themes; keyboard and screen-reader friendly (Radix primitives, real
headings, labelled controls, skip link, live regions for status). The editor is code-split,
so the bpmn-js bundle only loads when a map is opened.

```bash
make web-install      # once
make run              # API on :8000
make web-dev          # http://localhost:5173/app/ with hot reload (proxies the API)
make web-build        # production build served by the API at /app
make web-check        # typecheck + oxlint + prettier
```

`tests/test_web_e2e.py` drives the real app in Chromium against an in-process server:
sign in, upload two meetings, watch the jobs finish, open the merged map, apply a conflict
option, read a step's quotes, make a chat edit, create a key, and switch to dark mode. It fails
on any console or CSP error.

## Organizations, keys, auth

Every API endpoint except `/health` needs an API key (the web app's static files don't):
`Authorization: Bearer t2b_…` (or `X-API-Key`). Keys belong to an organization and are
issued by an operator (there's no signup or SSO yet):

```bash
uv run python -m app.cli create-org "Acme Corp"      # prints org id + first key (shown once)
uv run python -m app.cli create-key <org_id> --name ci
uv run python -m app.cli revoke-key <prefix>
```

Only a SHA-256 of each key is stored. The editor asks for a key once and keeps it in that
browser's localStorage.

**Isolation** (`app/db/tenancy.py`): every table except `organizations` carries
`organization_id`. Scoping is enforced once, at the SQLAlchemy session, not per query:
- every ORM statement in a request session (selects, `get`, lazy loads, bulk update/delete)
  gets `organization_id = <caller's org>` added automatically;
- inserts are stamped with the caller's org, and rows for another org are refused;
- a session with no org and no explicit `system_session()` refuses to run queries at all
  (fails closed).

Another org's ids return 404, the same as ids that don't exist. `tests/test_tenancy.py`
walks every route from the OpenAPI schema with a second org's key (a new route is covered
automatically) and checks the session layer directly.

Data created before tenancy was migrated into "Default organization"
(`00000000-0000-0000-0000-000000000001`, project "Imported"). Give it a key with `create-key`.

## API

| Endpoint | |
|---|---|
| `POST /projects` `{name, retention_days?}` · `GET /projects` · `GET /projects/{id}` | a project groups meetings about one process |
| `DELETE /projects/{id}` | removes every row and stored object of the project (counts returned) |
| `POST /projects/{id}/transcripts` (multipart `file`) | upload text or audio into a project |
| `POST /transcripts/{id}/process` | enqueue: transcribe → extract → own map → **merge into the project map** |
| `GET /jobs/{id}` | `queued → (transcribing) → normalizing → extracting → converting → merging → done \| failed` |
| `GET /projects/{id}/conflicts[?status=open]` · `POST /conflicts/{id}/resolve` | meetings that disagree |
| `GET /maps/{id}/export/{bpmn,svg,png,md}` | BPMN 2.0 XML, diagram image, Markdown SOP |
| `GET /audit` | who uploaded / processed / edited / exported / deleted what |
| `GET /maps/{id}` | `{model, bpmn_xml, version, can_undo, errors, segments}`. The model is canonical; XML is derived |
| `POST /maps/{id}/chat` `{instruction}` | LLM returns patch ops → applied → new version (`reply`, `ops` in response) |
| `PUT /maps/{id}/bpmn` (body: BPMN XML) | save from the visual editor → parsed back into the model → new version |
| `POST /maps/{id}/undo` | back one version (409 at v1) |
| `GET /maps/{id}/versions` | history: version, source (extract/chat/visual), instruction |
| `GET /app/…` | the web app (see *Web app*); `/editor/{id}`, `/viewer/{id}`, `/settings` redirect into it |

```bash
H="Authorization: Bearer $T2B_KEY"
P=$(curl -sH "$H" -H 'Content-Type: application/json' -d '{"name":"Invoices"}' localhost:8000/projects | jq -r .id)
T=$(curl -sH "$H" -F file=@eval/gold/01_invoice_approval/transcript.vtt localhost:8000/projects/$P/transcripts | jq -r .id)
curl -sH "$H" -X POST localhost:8000/transcripts/$T/process
curl -sH "$H" localhost:8000/projects/$P          # merged_map_id once the job is done
open http://localhost:8000/app/maps/<merged_map_id>   # or just use the web app at /app
```

## Multi-meeting merge

`app/pipeline/merge.py`. Every processed transcript gets its own map, then is folded into
its project's **merged map**. The first meeting seeds it; each later one is merged on top,
including whatever users have edited since.

1. **Entity resolution:** lanes and nodes are matched one-to-one by embedding similarity
   (`MODEL_EMBED`; tasks embed name + role, events and gateways name only). Above
   `MERGE_AUTO_MATCH` (0.90) it's the same element; below `MERGE_REJECT` (0.70) it's different.
   Pairs in between are sent in one batch to the LLM ("merge" role, `MODEL_MERGE`) to confirm.
2. **Patch ops only:** matched nodes gain the new meeting's citations; new steps and roles
   are added; a new step between two existing ones replaces their direct link. Existing names
   and owners are never overwritten. The op list is stored on the map version
   (`source: merge`), so it can be replayed and undone.
3. **Conflicts, never silent:** `owner` (a different role does a matched step), `order`
   (two known steps reversed; the edge is not added), `condition` (same decision path,
   different condition; the existing one is kept), and `sequence` (a step gains a second
   "next" outside a gateway). Each becomes a `conflicts` row plus an open question on the map.
   The editor shows one button per option. Picking one **applies it to the map** (reassigns
   the step's role, sets the condition, keeps one "next" step, or swaps two adjacent steps)
   in the same version that closes the question: `POST /conflicts/{id}/resolve {"option": i}`.
   `{"option": null}` ("I fixed it myself") just closes it. Options that need a judgement call
   (reordering steps that aren't adjacent) return 422 with what to do instead.

Merged-map citations are qualified (`<transcript_id>:s3`), so each node lists every meeting
and line it came from, and the editor shows quotes across meetings.

**Merge eval:** `eval/gold_merge/<case>/` holds `transcript_N`, gold `model_N.json`, gold
merged `expected.json`, and `expected_conflicts` in `meta.yaml`. Metrics are the single-map
ones plus **duplicate task rate** and **conflict detection recall**.

```bash
uv run python -m eval.merge_eval                                                # real: extract + merge
uv run python -m eval.merge_eval --pipeline eval.merge_eval:gold_extraction_pipeline   # merge only
```

## Review tools

All template- or graph-based (no LLM) except the policy check, which reuses the merge's matching.

- **Speaker roles** (`GET/PUT /projects/{id}/speakers[/{name}]`): tag each speaker once as
  process owner, does the work, or observer. Every disagreement carries `sides` (the quotes
  behind each option, with speaker and role) and `owner_side` (the side the process owner
  backs, when only one side has them). Shown, never acted on.
- **Gaps** (`app/pipeline/gaps.py`, `GET /projects/{id}/gaps`, `POST …/gaps/{gap}/dismiss`):
  decisions with one described outcome, steps with no owner, dead ends, steps nothing leads
  to, and checks/approvals with no rejection path. Ids are stable, so dismissed gaps stay gone.
- **Both are true** (`POST /conflicts/{id}/resolve {"variant": {"question", "labels"}}`):
  instead of picking a side, adds a decision ("Which region?") with one labelled branch per
  version; each version keeps its evidence (`variant_ops` in `app/pipeline/merge.py`). Not for
  step-order disagreements (draw those by hand).
- **Agenda** (`app/agenda.py`, `GET /projects/{id}/agenda`, Markdown): every open
  disagreement, policy difference, gap and open question as a question, grouped by the people
  who described that part of the process.
- **Policy comparison** (`app/policy.py`): upload with `?purpose=policy` (.docx/.txt). It's
  extracted like a meeting but never merged; differences from the map (owner, condition,
  order, steps only in the policy, steps only in meetings) become conflicts with
  `origin: "policy"`, listed apart. Settle with an option ("change the map to the policy") or
  `{"note": "deviation" | "dismissed"}`. Rechecked after every merge; settled ones stay settled.
- **Sign-off** (`app/api/signoffs.py`): `POST /projects/{id}/signoffs {name, lane_ids}` returns
  a private link token (shown once; sha256 stored; 30 days; `DELETE /signoffs/{id}` revokes).
  The link opens `/app/review/<token>` with no account: only that person's steps, where each
  comes from and goes to, and the quotes behind it. Approve / request changes is recorded with
  the map version seen, and audited.

## Sign-up, workspaces, public demo

- **Magic-link sign-up** (`app/api/auth.py`): `POST /auth/magic-link {email}` emails a one-time
  link (15 min) via Resend (`RESEND_API_KEY`, `EMAIL_FROM`; without a key the link is logged).
  `POST /auth/verify {token}` signs the person in: their first sign-in creates their own
  workspace; an invitation link (`POST /invites {email}`) adds them to the inviting one. The
  browser gets an expiring session key (`SESSION_DAYS`), the same kind of key integrations use,
  so tenancy, rate limits and audit are unchanged. `GET /auth/me`, `/auth/switch`, `/auth/logout`,
  `/members`, `/invites`.
- **Public demo** (`app/demo.py`): with `DEMO_SANDBOXES=true` the sign-in page offers **Try the
  demo**: `POST /demo/sandbox` gives each visitor a fresh copy of the sample workspace (built
  with the gold extractions, no AI), deleted after `SANDBOX_HOURS` by an hourly worker job.
  Sandboxes and `DEMO_MODE=true` refuse anything that would call an AI provider (uploads,
  processing, chat edits, live interviews, AI ideas). Hosting: `fly.toml` + `docs/deploy-fly.md`.

## Review queue, corrections, improvements

- **Review queue** (`GET /maps/{id}/review`, `POST /maps/{id}/review/{node}`): every AI-drafted
  step, unchecked first, then uncited, then lowest confidence (flagged under 75%). Checking a
  step isn't an edit (no new version).
- **Corrections flywheel** (`app/corrections.py`): every human edit (visual save, chat edit) is
  diffed against the AI's version into `corrections` rows (rename, move, retype, delete, add,
  connect, disconnect). `GET /corrections` shows them. Sharing is opt-in per workspace
  (`PUT /workspace {share_corrections: off|anonymised|full}`): `scripts/export_corrections.py`
  exports consenting workspaces as eval cases (git-ignored `eval/corrections/local/`), and
  `python -m eval.corrections_eval` re-runs full cases and reports which fixes the drafting now
  gets right by itself.
- **Improvements** (`app/pipeline/improve.py`, `GET /maps/{id}/improvements`): free, explainable
  rules on the map's structure: automation candidates (people doing data work), work bouncing
  between teams, handoff hotspots, approvals in a row. `POST /maps/{id}/improvements/ai` asks the
  LLM for more ("edit" role, `prompts/improve_v1.md`), only when a person clicks.
- **Timers and sub-processes, if the data says so** (`app/pipeline/signals.py`): counts how many
  meetings describe waits/deadlines/reminders or separate sub-processes
  (`GET /insights/bpmn-elements`; across all real workspaces: `scripts/element_evidence.py`).
  Rule: add the BPMN element to extraction once ≥ 20% of at least 10 real meetings describe it.

## Live interviews

`POST /projects/{id}/live` starts one; the browser records with `MediaRecorder` and every
`LIVE_CHUNK_SECONDS` (default 180) sends one complete recording to
`POST /transcripts/{id}/live/chunks?index&offset`. The worker (`live_chunk`, `app/live.py`)
transcribes it, shifts timestamps onto the interview's timeline, appends the lines and redraws
the meeting's draft map from everything so far; chunks of one interview are serialised by a row
lock. `POST …/live/finish` processes and merges it like any meeting (reusing the draft map).
Each chunk costs transcription + extraction.

## Data handling

- **Retention:** `retention_days` per project. A daily arq cron (03:00) deletes each expired
  transcript's raw file and its text (segments), and marks it `content_expired`. Maps keep
  working; source quotes show "no longer available"; re-processing returns 410.
- **Delete project:** `DELETE /projects/{id}` removes the project's transcripts, jobs, maps,
  versions, conflicts and every stored object (all under `orgs/<org>/projects/<id>/`).
- **Audit log** (`audit_log`): create, upload, process, merge, edit (chat/visual/undo),
  resolve_conflict, export, delete, retention_purge, with the API key that did it.
  Entries hold metadata only (ids, counts, formats, never meeting text), so they are kept
  when a project is deleted, including the record of the deletion itself.

## Exports

`GET /maps/{id}/export/{fmt}`:
- `bpmn`: the XSD-valid BPMN 2.0 XML.
- `svg` / `png`: rendered by the same bpmn-js the editor uses, in headless Chromium via
  Playwright, so exports match the editor exactly. bpmn-js is bundled
  (`app/static/vendor/bpmn-viewer.production.min.js`), so the server makes no CDN calls. Needs
  `playwright install chromium` (it's in the Docker image), or set
  `EXPORT_BROWSER_CHANNEL=chrome` to use a local Chrome.
- `docx` / `pdf`: the same SOP as Word (python-docx) and PDF (printed by the export browser),
  converted from the Markdown so all three say the same thing.
- `POST /maps/{id}/push/camunda`: creates the BPMN as a file in Camunda 8 Web Modeler
  (`CAMUNDA_CLIENT_ID`/`_SECRET`/`_PROJECT_ID`; written to Camunda's documented API, **not yet
  tested against a live account**). Signavio next, once there's an account to build against.
- `md`: a written SOP (roles, numbered steps with owners, decisions with their conditions,
  parallel work, outcomes, open questions). Every step quotes the transcript lines it came
  from, with speaker, meeting and timestamp.

## Switching to Azure OpenAI

Config only. Set `LLM_PROVIDER=azure`, `LLM_API_BASE`, `LLM_API_VERSION`, `LLM_API_KEY`, the
`MODEL_*` deployment names (incl. `MODEL_EMBED`), and for audio `TRANSCRIBE_PROVIDER=azure`
+ `TRANSCRIBE_MODEL=<deployment>`. A missing endpoint or version fails at startup.

- **Unit proof:** `tests/test_llm_provider.py::test_azure_is_config_only_for_every_model_call`
  checks that structured calls, embeddings and transcription all go to the Azure endpoint and
  deployments when only the env changes.
- **Live proof** (manual, or the `smoke` CI job with secrets):
  `uv run python -m eval.smoke --audio eval/asr/samples/invoice_approval.m4a` runs both
  invoice meetings through filter, extract, repair, embed + merge, BPMN/XSD, SOP and
  transcription against the configured provider, and exits non-zero on any failure.

## Operations

- **HTTPS:** `DOMAIN=maps.example.com docker compose --profile tls up -d` puts Caddy
  (`deploy/Caddyfile`) in front of the API with automatic Let's Encrypt certificates
  (`localhost` gets Caddy's local CA). The API runs with `--proxy-headers`, so it knows the
  request was HTTPS and sends HSTS. In production don't publish port 8000.
- **Security headers:** every response gets `nosniff`, `no-referrer` and `X-Frame-Options:
  DENY`. HTML pages get a strict CSP: same-origin scripts only, no inline script. bpmn-js,
  its CSS and fonts are bundled into the web app build, so the browser loads nothing
  third-party.
- **CORS:** off unless `CORS_ORIGINS='["https://app.example.com"]'` is set (the editor is
  same-origin; API clients aren't browsers).
- **Rate limits** (per API key, Redis fixed one-minute windows): `RATE_LIMIT_PER_MINUTE`
  (300) for all calls, and `RATE_LIMIT_HEAVY_PER_MINUTE` (30) for upload, process, chat and
  image export. Over the limit returns 429 with `Retry-After`.
- **Quotas:** `python -m app.cli set-quota <org_id> 500` caps transcripts processed per
  calendar month (429 when reached); no number = unlimited. `GET /usage` shows usage and limits.
- **API keys:** the web app's Settings page (and `GET/POST /keys`, `DELETE /keys/{id}`): list, create
  (shown once) and revoke the organization's keys. You can't revoke the last active key.
  Every change is audited.
- **Metrics (Prometheus):** API at `GET /metrics` with `Authorization: Bearer $METRICS_TOKEN`
  (404 when unset); worker exporter on `METRICS_PORT` (9100). Series: `t2b_http_requests_total`
  / `t2b_http_request_seconds` (by route template, never ids), `t2b_jobs_total{status}`,
  `t2b_job_stage_seconds{stage}`, `t2b_llm_calls_total{role,outcome}`,
  `t2b_llm_call_seconds{role}`, `t2b_exports_total{format}`. Langfuse still traces each LLM call.
- **Backups:** `make backup` (or `scripts/backup.sh [dir]`) writes `db.dump` (pg_dump) and
  every stored object. `make restore DIR=backups/<ts> [DB=app_restore BUCKET=…]` restores,
  optionally side by side so you can verify a backup without touching live data. Managed
  deployments (RDS/S3) should also use provider snapshots and bucket versioning.
- **Exports** reuse one warm headless Chromium on a dedicated thread (~0.2 s per image after
  the first).

## CI

`.github/workflows/ci.yml`: the `test` job (lint + full suite with Postgres/Redis/MinIO,
ffmpeg and Chromium) runs on every push and PR. The `smoke` job runs the live pipeline for
`openai` and `azure` on demand and weekly, only where credentials are configured
(secrets: `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`; variables:
model/deployment names per role, `AZURE_OPENAI_API_VERSION`).

## Editing

The **ProcessModel JSON is the source of truth**. BPMN XML is regenerated from it on every
change and always passes the XSD before it's stored.

- **Chat** (`app/pipeline/edit.py`): the LLM ("edit" role, `prompts/edit_v1.md`) returns typed
  patch ops, never a whole model: `add_task`, `remove_node`, `rename_node`, `merge_tasks`,
  `split_task`, `reassign_lane`, `add_lane`, `add_gateway`, `connect`, `disconnect`,
  `set_condition`, `resolve_open_question`. They're applied deterministically and
  all-or-nothing. If an op references something that doesn't exist, the LLM gets one retry
  with the error; otherwise you get a 422. A reply that's only a clarifying question changes
  nothing. Edits are validated (issues shown in the editor) but not auto-repaired, so a fix
  never fights the user.
- **Visual** (`app/pipeline/parse_bpmn.py`): the editor PUTs bpmn-js's saved XML. Elements
  match the model by id (`Node_<id>`, `Lane_<id>`, `Flow_<id>`). Elements the editor
  created get no citations, confidence 1.0 and `user_added: true`. Decision paths labelled
  only by name become conditions. Elements the model can't represent (sub-processes,
  intermediate events, inclusive gateways…) are rejected with 422, not dropped. The XML
  parser has entities, DTDs and network disabled (no XXE).
- **Versions & undo** (`app/maps.py`, `map_versions` table): every change is a version
  with its source, and for chat its ops and instruction. Undo moves back one version; a new
  edit after an undo discards the undone ones (a normal undo stack).
- **Layout preservation:** before regenerating, node positions are read from the current
  diagram (lane-relative y), so anything the user dragged stays put. A step inserted between
  kept nodes is placed right after its predecessors, and everything downstream shifts right
  as a group (its arrangement kept) to make room. Hand-drawn edge routes are kept while both
  ends stay put, and recomputed once either moves.
- **Editor:** the web app's map page (see *Web app*).

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
    (default 600 s ≈ 3.6 MB, far under the 25 MB API limit). Chunks overlap by
    `TRANSCRIBE_CHUNK_OVERLAP_SECONDS` (3 s), so a word at a cut is heard whole. Each chunk
    owns its own 10-minute slice, and `stitch()` keeps a segment only from the chunk that owns
    its start, so the overlap never duplicates speech. Timestamps are shifted onto the
    recording timeline and kept monotonic and in bounds.
  - Diarization: models whose name contains `diarize` are called with `diarized_json`.
    Speaker labels restart at "A" on every request, so after chunk 1 the adapter sends 2–10 s
    voice clips of up to 4 speakers as `known_speaker_references`. Later chunks then reuse
    the same labels. A voice not among the references stays distinct (`Speaker C (part 3)`)
    rather than being guessed.
  - Other models: `whisper*` → timed segments; anything else → text split into sentences
    with approximate timestamps. All speakers are `Unknown speaker`, and
    `transcripts.diarization_available = false` so the UI can ask the user to label speakers.
    Unknown-speaker segments are never merged.
- **Deepgram adapter** (`transcribe/deepgram.py`, `TRANSCRIBE_PROVIDER=deepgram`,
  `TRANSCRIBE_MODEL=nova-3`, `DEEPGRAM_API_KEY`): one request per recording (Deepgram takes up
  to 2 GB), so there's no chunking and speaker numbers stay consistent all meeting. Audio is
  re-encoded to MP3 before upload. Uses `utterances` with `diarize`. Compare it with OpenAI via
  `eval/asr_benchmark.py --configs openai:<model> deepgram:nova-3`.

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

As a last line of defence the converter also drops duplicate ids and dangling flows, and puts
unknown-lane nodes in an "Unassigned" lane, so the XML stays valid even when validation
problems are left unresolved.

## Manual Camunda Modeler check

The XSD check is automated (`tests/test_convert.py`, `tests/test_integration.py`). Camunda
Modeler is a manual check per release:

1. Process a transcript, open its map in the web app, choose **Export → BPMN 2.0**.
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
app/pipeline/   ingest, transcribe/, normalize, extract, validate, convert, edit, parse_bpmn, merge, export, run
web/            React web app (Vite, shadcn/ui, Tailwind), built into app/static/app
app/static/     built web app (gitignored) + vendored bpmn-js viewer for server-side exports
app/maps.py     map versions: create / commit / undo
app/projects.py merge into project, delete project, retention
app/auth.py     API keys -> org-scoped DB session
app/audit.py    audit log helper
app/cli.py      create-org / create-key / revoke-key
app/db/tenancy.py  session-level tenant isolation
app/storage.py  S3/MinIO put/get
app/db/         SQLAlchemy base + Alembic migrations
app/workers/    arq worker settings
eval/           gold cases, metrics, runner; gold_merge/ + merge_eval.py; asr_benchmark.py + asr/; smoke.py
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
make eval ARGS="--pipeline eval.stub_pipeline:pipeline --match lexical"   # oracle stub, no LLM
make eval ARGS="--pipeline mymodule:fn --match lexical --threshold 0.75"  # any Callable[[Path], ProcessModel]
```

Reports land in `eval/reports/<timestamp>.{md,json}` (gitignored) so runs can be diffed.

Metrics (macro-averaged over cases): task recall, task precision, lane accuracy, gateway
recall, flow-edge F1. Nodes are matched one-to-one within kind (task / gateway type /
event type). `--match semantic` (default) pairs tasks, gateways and lanes by meaning, using
the merge step's resolver (embeddings; the "merge" model confirms close calls), so
"Send invoice back to supplier" counts as "Return invoice to supplier". `--match lexical`
uses spelling similarity (`difflib`, `--threshold`, default 0.8): no LLM needed, but it
underscores paraphrases. Events match on type alone. Lane accuracy and edge F1 are computed through that matching,
so different ids in the prediction don't matter.

The default is the real pipeline (`app.pipeline.run:eval_pipeline`). If a case fails (e.g.
no API key), its traceback goes in the report and the run continues.
`eval.stub_pipeline` is an oracle (returns `expected.json`) — it proves the
plumbing, not quality. The 2 included cases are synthetic; add ≥10 real/permission-cleared
cases before Phase 1 is done.

## Notes

- Compose maps Postgres to host port **5433** to avoid clashing with a local Postgres.
- MinIO uses `cgr.dev/chainguard/minio` — `minio/minio` is no longer pullable from Docker Hub.
