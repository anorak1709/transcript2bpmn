import os
from abc import ABC, abstractmethod
from typing import Any, TypeVar

import litellm
from litellm.types.llms.openai import ResponsesAPIResponse
from openai.lib._pydantic import (
    to_strict_json_schema,  # ponytail: private but maintained; same helper the OpenAI SDK uses
)
from pydantic import BaseModel

from app.core.config import ModelRole, Settings, get_settings

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    @abstractmethod
    def structured(
        self, prompt: str, input: str, schema: type[T], model_role: ModelRole, metadata: dict[str, Any] | None = None
    ) -> T:
        """Run `prompt` (instructions) over `input` and return a validated `schema` instance.

        `metadata` is attached to the trace (e.g. repair attempt number, error codes)."""


class LiteLLMProvider(LLMProvider):
    """OpenAI Responses API with strict JSON Schema output, via LiteLLM.

    Provider, base URL, key and per-role model names all come from Settings,
    so OpenAI -> Azure OpenAI is an env change only.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        _enable_tracing(self.settings)

    def structured(
        self, prompt: str, input: str, schema: type[T], model_role: ModelRole, metadata: dict[str, Any] | None = None
    ) -> T:
        s = self.settings
        kwargs: dict[str, Any] = {}
        if s.llm_api_base:
            kwargs["api_base"] = s.llm_api_base
        if s.llm_api_key:
            kwargs["api_key"] = s.llm_api_key
        if s.llm_api_version:
            kwargs["api_version"] = s.llm_api_version
        resp = litellm.responses(
            model=s.model_for(model_role),
            instructions=prompt,
            input=input,
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema.__name__,
                    "schema": to_strict_json_schema(schema),
                    "strict": True,
                }
            },
            metadata={"model_role": model_role, **(metadata or {})},
            **kwargs,
        )
        assert isinstance(resp, ResponsesAPIResponse)  # sync, non-streaming call
        return schema.model_validate_json(resp.output_text)


def _enable_tracing(s: Settings) -> None:
    """Send every LiteLLM call (prompt, model, tokens, latency, cost) to Langfuse when keys are set."""
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        return
    # LiteLLM's Langfuse logger reads these from the process env, not from Settings.
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", s.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", s.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_HOST", s.langfuse_host)
    if "langfuse_otel" not in litellm.callbacks:
        litellm.callbacks.append("langfuse_otel")
