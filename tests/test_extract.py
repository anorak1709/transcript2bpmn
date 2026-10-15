import pytest

from app.models.transcript import Segment
from app.pipeline import extract
from app.pipeline.ingest import parse
from app.pipeline.normalize import normalize
from app.pipeline.prompts import load_prompt
from tests.conftest import GOLD, FakeLLM, gold_model


def _segments(case: str) -> list[Segment]:
    path = next((GOLD / case).glob("transcript.*"))
    return normalize(parse(path.name, path.read_bytes()))


def test_filter_drops_chatter_and_extract_sees_only_relevant() -> None:
    segs = _segments("02_employee_onboarding")
    llm = FakeLLM(gold_model("02_employee_onboarding"))
    model = extract.extract(llm, segs)

    roles = [role for role, _ in llm.calls]
    assert roles == ["filter", "extract"]
    extract_input = llm.calls[1][1]
    assert "game" not in extract_input and "lunch" not in extract_input
    assert "[s3] Dana:" in extract_input
    assert model.name == "New employee onboarding"


def test_batches_respect_size_and_keep_order() -> None:
    segs = [Segment(segment_id=f"s{i}", speaker="A", start_ts=None, end_ts=None, text="x" * 40) for i in range(10)]
    out = extract.batches(segs, max_chars=100)
    assert [len(b) for b in out] == [2, 2, 2, 2, 2]
    assert [s for b in out for s in b] == segs


def test_every_node_ends_up_citing_a_valid_segment() -> None:
    model = gold_model("01_invoice_approval")
    model.nodes[0].source_segment_ids = ["s99"]  # invented
    model.nodes[1].source_segment_ids = []  # missing
    conf = model.nodes[1].confidence
    fixed = extract.enforce_citations(model, {"s1", "s2", "s3", "s4"})

    assert all(n.source_segment_ids and set(n.source_segment_ids) <= {"s1", "s2", "s3", "s4"} for n in fixed.nodes)
    assert fixed.nodes[1].source_segment_ids == ["s1"]  # borrowed from its neighbour t_match
    assert fixed.nodes[1].confidence == conf / 2


def test_uncited_graph_falls_back_to_first_segment() -> None:
    model = gold_model("02_employee_onboarding")
    for n in model.nodes:
        n.source_segment_ids = []
    fixed = extract.enforce_citations(model, {"s10", "s2", "s3"})
    assert {tuple(n.source_segment_ids) for n in fixed.nodes} == {("s2",)}


def test_prompts_are_versioned_files() -> None:
    assert load_prompt(extract.FILTER_PROMPT).strip()
    assert "source_segment_ids" in load_prompt(extract.EXTRACT_PROMPT)


def test_windows_overlap_and_cover_everything() -> None:
    segs = [Segment(segment_id=f"s{i}", speaker="A", start_ts=None, end_ts=None, text="x" * 100) for i in range(1, 21)]
    windows = extract.extraction_windows(segs, max_chars=500)
    assert [len(w) for w in windows][0] == 5
    for a, b in zip(windows, windows[1:], strict=False):
        assert a[-extract.WINDOW_OVERLAP :] == b[: extract.WINDOW_OVERLAP]  # shared context at each cut
    assert {s.segment_id for w in windows for s in w} == {s.segment_id for s in segs}
    assert extract.extraction_windows(segs, max_chars=10_000) == [segs]  # short meetings: one call


def test_long_meeting_is_extracted_in_windows_without_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from app.models.process import TASK_TYPES

    monkeypatch.setattr(get_settings(), "extract_max_chars", 150)  # force several windows
    segs = _segments("02_employee_onboarding")
    llm = FakeLLM(gold_model("02_employee_onboarding"))  # every window "sees" the same steps
    model = extract.extract_model(llm, segs)

    assert sum(role == "extract" for role, _ in llm.calls) > 2
    tasks = [n.name for n in model.nodes if n.type in TASK_TYPES]
    assert len(tasks) == len(set(tasks)) == 4  # the merge folded the repeats together
    valid = {s.segment_id for s in segs}
    assert all(n.source_segment_ids and set(n.source_segment_ids) <= valid for n in model.nodes)


def test_llm_cleanup_keeps_ids_and_rejects_rewrites() -> None:
    from typing import Any

    from app.pipeline.normalize import CleanBatch, llm_cleanup

    class Cleaner(FakeLLM):
        def structured(self, prompt: str, input: str, schema: Any, model_role: Any, metadata: Any = None) -> Any:
            assert schema is CleanBatch and model_role == "filter"
            return CleanBatch.model_validate(
                {
                    "segments": [
                        {"segment_id": "s1", "text": "We enter the invoice in SAP."},  # ASR fix
                        {"segment_id": "s2", "text": ""},  # pure filler: dropped
                        {"segment_id": "s3", "text": "Then we pay it. " * 10},  # the model padded it: rejected
                        {"segment_id": "s99", "text": "invented"},  # unknown id: ignored
                    ]
                }
            )

    segs = [
        Segment(segment_id=f"s{i}", speaker="A", start_ts=None, end_ts=None, text=t)
        for i, t in enumerate(["We enter the invoice in sap, sap.", "Yeah, so.", "Then we pay it."], 1)
    ]
    out = llm_cleanup(Cleaner(gold_model("01_invoice_approval")), segs)
    assert [(s.segment_id, s.text) for s in out] == [("s1", "We enter the invoice in SAP."), ("s3", "Then we pay it.")]
