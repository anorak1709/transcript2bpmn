import math
import re
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import ModelRole
from app.llm.provider import LLMProvider
from app.models.process import ProcessModel
from app.pipeline.extract import RelevanceBatch, RelevanceLabel
from app.pipeline.merge import PairVerdict, PairVerdicts

GOLD = Path(__file__).parent.parent / "eval" / "gold"
T = TypeVar("T", bound=BaseModel)


def gold_model(case: str) -> ProcessModel:
    return ProcessModel.model_validate_json((GOLD / case / "expected.json").read_text())


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


# --- Integration plumbing (tests that need the compose services) ------------------------------

import uuid  # noqa: E402
from dataclasses import dataclass  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402


def services_up() -> bool:
    from app import storage
    from app.db.tenancy import system_session

    try:
        with system_session() as db:
            db.execute(text("select 1 from organizations limit 1"))
        storage._client()
        return True
    except Exception:
        return False


needs_services = pytest.mark.skipif(not services_up(), reason="compose services not running / not migrated")


class RecordingQueue:
    """Stands in for the arq pool so a running worker can't pick up test jobs."""

    def __init__(self) -> None:
        self.jobs: list[tuple[Any, ...]] = []

    async def enqueue_job(self, *args: Any, **kwargs: Any) -> None:
        self.jobs.append(args)


@dataclass
class TenantCtx:
    org_id: str
    key: str
    client: TestClient
    project_id: str
    queue: RecordingQueue

    def upload(self, filename: str, data: bytes, project_id: str | None = None) -> Any:
        return self.client.post(
            f"/projects/{project_id or self.project_id}/transcripts", files={"file": (filename, data)}
        )

    def process(self, transcript_id: str, llm: LLMProvider, transcriber: Any = None) -> dict[str, Any]:
        from app.workers.jobs import run_job

        r = self.client.post(f"/transcripts/{transcript_id}/process")
        assert r.status_code == 202, r.text
        run_job(r.json()["id"], llm, transcriber)
        job: dict[str, Any] = self.client.get(f"/jobs/{r.json()['id']}").json()
        return job


def make_tenant(retention_days: int | None = None) -> TenantCtx:
    from app.auth import create_key, create_org
    from app.db.tenancy import system_session
    from app.main import app

    with system_session() as db:
        org = create_org(db, f"Test org {uuid.uuid4().hex[:6]}")
        key = create_key(db, org.id)
        db.commit()
    queue = RecordingQueue()
    app.state.arq = queue  # lifespan isn't run (no `with`), so no real Redis pool is created
    client = TestClient(app, headers={"Authorization": f"Bearer {key}"})
    project = client.post("/projects", json={"name": "Invoices", "retention_days": retention_days})
    assert project.status_code == 201, project.text
    return TenantCtx(org.id, key, client, project.json()["id"], queue)


@pytest.fixture
def tenant() -> TenantCtx:
    return make_tenant()


@pytest.fixture
def other_tenant() -> TenantCtx:
    return make_tenant()
