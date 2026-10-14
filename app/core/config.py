from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelRole = Literal["extract", "filter", "repair", "edit", "merge"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://app:app@localhost:5433/app"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "transcripts"

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

    # Diagram image export (headless Chromium). None = Playwright's bundled Chromium;
    # "chrome" = a locally installed Google Chrome (handy in dev).
    export_browser_channel: str | None = None

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Merge entity resolution: cosine >= auto -> same step; < reject -> different; else ask the LLM.
    merge_auto_match: float = 0.90
    merge_reject: float = 0.70

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
