from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ModelRole = Literal["extract", "filter", "repair", "edit"]


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

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    def model_for(self, role: ModelRole) -> str:
        name: str = getattr(self, f"model_{role}")
        if not name:
            raise ValueError(f"MODEL_{role.upper()} is not set")
        return f"{self.llm_provider}/{name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
