from app.models.transcript import Segment
from app.pipeline import extract
from app.pipeline.ingest import parse
from app.pipeline.normalize import normalize
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
    assert extract.load_prompt(extract.FILTER_PROMPT).strip()
    assert "source_segment_ids" in extract.load_prompt(extract.EXTRACT_PROMPT)
