from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelRole = Literal["extract", "filter", "repair", "edit", "merge"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://app:app@localhost:5433/app"
    redis_url: str = "redis://localhost:6379/0"
    job_queue: str = "arq:queue"  # API enqueues here, worker consumes here

    # Browser origins allowed to call the API cross-origin (JSON list). Empty = same-origin only.
    cors_origins: list[str] = []
    # Prometheus: GET /metrics needs `Authorization: Bearer <token>`; unset disables it.
    metrics_token: str | None = None
    metrics_port: int = 9100  # worker's exporter

    # Per API key, per minute. 0 disables. "heavy" = upload, process, chat, image export.
    rate_limit_per_minute: int = 300
    rate_limit_heavy_per_minute: int = 30

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "transcripts"
    s3_region: str | None = None  # Supabase/B2/R2 need theirs; MinIO and Tigris don't

    # LiteLLM provider prefix: "openai", "azure", ... Switching provider is config only.
    llm_provider: str = "openai"
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    llm_api_version: str | None = None  # Azure only

    # No defaults on purpose: model names are picked per deployment, never hardcoded.
    model_extract: str = ""
    model_filter: str = ""
    model_repair: str = ""
    model_edit: str = ""
    model_merge: str = ""  # confirms ambiguous "same step?" pairs when merging meetings
    model_embed: str = ""  # embeddings for entity resolution across meetings

    # Audio transcription (fallback input path). Model name always from env.
    transcribe_provider: str = "openai"
    transcribe_model: str = ""
    transcribe_api_key: str | None = None  # falls back to LLM_API_KEY
    transcribe_api_base: str | None = None  # Azure: falls back to LLM_API_BASE
    transcribe_api_version: str | None = None  # Azure only; falls back to LLM_API_VERSION
    transcribe_chunk_seconds: int = 600  # keeps each request well under the 25 MB API limit
    deepgram_api_key: str | None = None  # TRANSCRIBE_PROVIDER=deepgram
    deepgram_api_base: str = "https://api.deepgram.com"
    deepgram_diarize: bool = True
    transcribe_chunk_overlap_seconds: float = 3.0  # audio shared by neighbouring chunks (no word cut in half)

    # Diagram image export (headless Chromium). None = Playwright's bundled Chromium;
    # "chrome" = a locally installed Google Chrome (handy in dev).
    export_browser_channel: str | None = None

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Optional LLM cleanup of transcript text after the deterministic rules ("filter" role).
    # Mostly useful for audio (ASR) transcripts; costs one extra pass over the transcript.
    normalize_llm_cleanup: bool = False

    # Transcripts longer than this (characters of relevant text, ~4 chars/token) are extracted
    # in overlapping windows and merged. Keep well under the extract model's context window.
    extract_max_chars: int = 60_000

    # Merge entity resolution: cosine >= auto -> same step; < reject -> different; else ask the LLM.
    merge_auto_match: float = 0.90
    merge_reject: float = 0.70

    # Public URL of the web app, used in magic-link and invite emails.
    public_url: str = "http://localhost:8000"
    # Header the platform's proxy sets to the real client IP (Fly: fly-client-ip). Empty: the socket
    # peer, which uvicorn's --proxy-headers takes from X-Forwarded-For (spoofable behind some proxies).
    client_ip_header: str = "fly-client-ip"
    # Free hosts without a worker (Render free): run the hourly purges inside the web process.
    in_process_crons: bool = False
    # Sign-up by email magic link. No RESEND_API_KEY = links are written to the log (dev only).
    resend_api_key: str | None = None
    email_from: str = "Transcript to BPMN <login@example.com>"
    magic_link_minutes: int = 15
    session_days: int = 30
    # Public demo: one-click sandbox workspaces (no AI), deleted after sandbox_hours.
    demo_sandboxes: bool = False
    sandbox_hours: int = 24
    # Demo deployment: nothing anywhere may call an AI provider (uploads aren't processed).
    demo_mode: bool = False
    # Live interviews: the browser sends one complete audio chunk this often.
    live_chunk_seconds: int = 180
    # Send to Camunda (Web Modeler API, client credentials). Unset = the button is hidden.
    camunda_client_id: str | None = None
    camunda_client_secret: str | None = None
    camunda_project_id: str | None = None
    camunda_oauth_url: str = "https://login.cloud.camunda.io/oauth/token"
    camunda_audience: str = "api.cloud.camunda.io"
    camunda_modeler_url: str = "https://modeler.cloud.camunda.io"

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        """Hosted Postgres (Fly, Heroku-style) hands out postgres://; SQLAlchemy needs the driver."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix) :]
        return v

    @model_validator(mode="after")
    def _azure_needs_endpoint_and_version(self) -> "Settings":
        # Fail at startup with a clear message instead of on the first LLM call.
        for prefix, provider, base, version in (
            ("LLM", self.llm_provider, self.llm_api_base, self.llm_api_version),
            (
                "TRANSCRIBE",
                self.transcribe_provider,
                self.transcribe_api_base or self.llm_api_base,
                self.transcribe_api_version or self.llm_api_version,
            ),
        ):
            if provider == "azure" and not (base and version):
                raise ValueError(f"{prefix}_PROVIDER=azure needs an endpoint (API_BASE) and API_VERSION")
        return self

    def model_for(self, role: ModelRole | Literal["embed"]) -> str:
        name: str = getattr(self, f"model_{role}")
        if not name:
            raise ValueError(f"MODEL_{role.upper()} is not set")
        return f"{self.llm_provider}/{name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
