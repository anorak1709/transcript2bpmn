from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import ModelRole
from app.llm.provider import LLMProvider
from app.models.process import ProcessModel
from app.pipeline.extract import RelevanceBatch, RelevanceLabel

GOLD = Path(__file__).parent.parent / "eval" / "gold"
T = TypeVar("T", bound=BaseModel)


def gold_model(case: str) -> ProcessModel:
    return ProcessModel.model_validate_json((GOLD / case / "expected.json").read_text())


class FakeLLM(LLMProvider):
    """Scripted LLM: labels segments containing `noise` words irrelevant, returns `model`."""

    def __init__(self, model: ProcessModel, noise: tuple[str, ...] = ("game", "lunch")) -> None:
        self.model = model
        self.noise = noise
        self.calls: list[tuple[ModelRole, str]] = []

    def structured(
        self, prompt: str, input: str, schema: type[T], model_role: ModelRole, metadata: dict[str, Any] | None = None
    ) -> T:
        self.calls.append((model_role, input))
        if schema is RelevanceBatch:
            labels = []
            for line in input.splitlines():
                sid = line[1 : line.index("]")]
                relevant = not any(w in line.lower() for w in self.noise)
                labels.append(RelevanceLabel(segment_id=sid, process_relevant=relevant, reason="fake"))
            return schema.model_validate(RelevanceBatch(labels=labels).model_dump())
        return schema.model_validate(self.model.model_dump())
