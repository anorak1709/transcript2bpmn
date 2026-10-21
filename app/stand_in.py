"""A stand-in LLM that answers from known-good extractions: no network, no credits.

Used by the test suite and to build the public demo's sandbox workspaces (app/demo.py).
"""

import math
import re
import zlib
from collections import Counter
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import ModelRole
from app.llm.provider import LLMProvider
from app.models.process import ProcessModel
from app.pipeline.extract import RelevanceBatch, RelevanceLabel
from app.pipeline.merge import PairVerdict, PairVerdicts

T = TypeVar("T", bound=BaseModel)


def _tokens(text: str) -> Counter[str]:
    return Counter(re.sub(r"\d[\d,]*", "<num>", w) for w in re.findall(r"[\w$,]+", text.lower().replace("$", "")))


def lexical_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic stand-in for an embedding model: hashed bag of words, numbers folded to
    one token (so "$5,000" ~ "$10,000"). Similar wording -> high cosine, like real embeddings."""
    out = []
    for t in texts:
        v = [0.0] * 512
        for tok, c in _tokens(t).items():
            v[zlib.crc32(tok.encode()) % 512] += c  # stable across runs, unlike hash()
        out.append(v)
    return out


def lexical_same(a: str, b: str) -> bool:
    """Fake 'merge' LLM: same step if the names (without the [role]) share most words."""
    ta, tb = _tokens(a.split(" [")[0]), _tokens(b.split(" [")[0])
    dot = sum(ta[k] * tb[k] for k in ta)
    norm = math.sqrt(sum(v * v for v in ta.values()) * sum(v * v for v in tb.values()))
    return bool(norm) and dot / norm >= 0.6


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
        if schema is PairVerdicts:
            verdicts = []
            for line in input.splitlines():
                pid, existing, new, _ = (part.strip() for part in line.split(" | "))
                same = lexical_same(existing.removeprefix("existing: "), new.removeprefix("new: "))
                verdicts.append(PairVerdict(pair_id=pid, same=same, reason="fake"))
            return schema.model_validate(PairVerdicts(verdicts=verdicts).model_dump())
        return schema.model_validate(self.model.model_dump())

    def embed(self, texts: list[str]) -> list[list[float]]:
        return lexical_embed(texts)
