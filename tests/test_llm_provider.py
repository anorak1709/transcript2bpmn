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
