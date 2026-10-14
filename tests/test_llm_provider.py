from typing import Any

import litellm
import pytest
from litellm.types.llms.openai import ResponsesAPIResponse
from pydantic import BaseModel

from app.core.config import Settings
from app.llm.provider import LiteLLMProvider

REPLY = {
    "id": "r1",
    "created_at": 0,
    "output": [
        {
            "type": "message",
            "id": "m1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": '{"text": "hi"}', "annotations": []}],
        }
    ],
}


class Answer(BaseModel):
    text: str


def _call(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> dict[str, Any]:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    captured: dict[str, Any] = {}

    def fake_responses(**kwargs: Any) -> ResponsesAPIResponse:
        captured.update(kwargs)
        return ResponsesAPIResponse.model_validate(REPLY)

    monkeypatch.setattr(litellm, "responses", fake_responses)
    out = LiteLLMProvider(Settings(_env_file=None)).structured("p", "i", Answer, "extract")
    assert out == Answer(text="hi")
    return captured


def test_env_config_selects_model_and_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    openai = _call(monkeypatch, {"LLM_PROVIDER": "openai", "MODEL_EXTRACT": "model-a"})
    assert openai["model"] == "openai/model-a"
    assert "api_version" not in openai

    azure = _call(
        monkeypatch,
        {
            "LLM_PROVIDER": "azure",
            "MODEL_EXTRACT": "my-extract-deployment",
            "LLM_API_BASE": "https://example.openai.azure.com",
            "LLM_API_VERSION": "2025-04-01-preview",
        },
    )
    assert azure["model"] == "azure/my-extract-deployment"
    assert azure["api_base"] == "https://example.openai.azure.com"
    assert azure["api_version"] == "2025-04-01-preview"


def test_strict_schema_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    fmt = _call(monkeypatch, {"MODEL_EXTRACT": "m"})["text"]["format"]
    assert fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["required"] == ["text"]


def test_missing_model_role_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_EDIT", raising=False)
    with pytest.raises(ValueError, match="MODEL_EDIT"):
        Settings(_env_file=None).model_for("edit")


AZURE_ENV = {
    "LLM_PROVIDER": "azure",
    "LLM_API_BASE": "https://acme.openai.azure.com",
    "LLM_API_VERSION": "2025-04-01-preview",
    "LLM_API_KEY": "azure-key",
    "MODEL_EXTRACT": "extract-deploy",
    "MODEL_EMBED": "embed-deploy",
    "TRANSCRIBE_PROVIDER": "azure",
    "TRANSCRIBE_MODEL": "transcribe-deploy",
}


def test_azure_is_config_only_for_every_model_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Every outbound model call (structured LLM, embeddings, transcription) goes to Azure
    deployments when only the env changes."""
    for k, v in AZURE_ENV.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)

    calls: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(
        litellm,
        "responses",
        lambda **kw: calls.setdefault("responses", kw) and ResponsesAPIResponse.model_validate(REPLY),
    )
    monkeypatch.setattr(
        litellm,
        "embedding",
        lambda **kw: calls.setdefault("embedding", kw) and type("E", (), {"data": [{"embedding": [1.0]}]})(),
    )
    provider = LiteLLMProvider(s)
    provider.structured("p", "i", Answer, "extract")
    provider.embed(["x"])
    for name in ("responses", "embedding"):
        assert calls[name]["api_base"] == "https://acme.openai.azure.com"
        assert calls[name]["api_version"] == "2025-04-01-preview"
    assert calls["responses"]["model"] == "azure/extract-deploy"
    assert calls["embedding"]["model"] == "azure/embed-deploy"

    from app.pipeline.transcribe import get_transcriber
    from app.pipeline.transcribe import openai as adapter

    made: dict[str, Any] = {}
    monkeypatch.setattr(adapter, "AzureOpenAI", lambda **kw: made.update(kw) or object())
    t = get_transcriber(s)
    assert made == {
        "api_key": "azure-key",
        "azure_endpoint": "https://acme.openai.azure.com",
        "api_version": "2025-04-01-preview",
    }
    assert t.model == "transcribe-deploy"  # type: ignore[attr-defined]


def test_incomplete_azure_config_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.setenv("LLM_API_BASE", "https://acme.openai.azure.com")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)
    with pytest.raises(ValueError, match="LLM_PROVIDER=azure needs"):
        Settings(_env_file=None)
