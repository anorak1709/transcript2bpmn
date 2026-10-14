from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from app.core.config import ModelRole
from app.llm.provider import LLMProvider
from app.models.process import Flow, Lane, Node, NodeType, ProcessModel
from app.models.transcript import Segment
from app.pipeline.convert import to_bpmn, validate_xsd
from app.pipeline.validate import MAX_REPAIR_ATTEMPTS, repair, validate
from tests.conftest import gold_model

T = TypeVar("T", bound=BaseModel)
BROKEN = Path(__file__).parent / "fixtures" / "broken_extraction.json"
SEGMENTS = [
    Segment(segment_id=f"s{i}", speaker="Priya", start_ts=None, end_ts=None, text=t)
    for i, t in enumerate(
        [
            "Invoices land and we enter them.",
            "Over 5k goes to finance.",
            "Under 5k AP approves.",
            "Then the payment run pays it.",
        ],
        1,
    )
]


def node(id: str, type: NodeType = "user_task", lane: str = "l1") -> Node:
    return Node(id=id, type=type, name=id, lane_id=lane, source_segment_ids=["s1"], confidence=1)


def flow(src: str, tgt: str, cond: str | None = None, id: str | None = None) -> Flow:
    return Flow(id=id or f"{src}->{tgt}", source_id=src, target_id=tgt, condition=cond)


def model(nodes: list[Node], flows: list[Flow], lanes: list[str] = ["l1"]) -> ProcessModel:  # noqa: B006
    return ProcessModel(
        name="t", lanes=[Lane(id=lid, name=lid) for lid in lanes], nodes=nodes, flows=flows, open_questions=[]
    )


def linear(*middle: Node) -> ProcessModel:
    """start -> middle... -> end, the valid baseline each test breaks one way."""
    nodes = [node("start", "start_event"), *middle, node("end", "end_event")]
    return model(nodes, [flow(a.id, b.id) for a, b in zip(nodes, nodes[1:], strict=False)])


def codes(m: ProcessModel) -> list[str]:
    return sorted(e.code for e in validate(m))


def test_valid_models_have_no_errors() -> None:
    assert validate(linear(node("a"), node("b"))) == []
    assert validate(gold_model("01_invoice_approval")) == []
    assert validate(gold_model("02_employee_onboarding")) == []


def test_duplicate_ids() -> None:
    m = linear(node("a"))
    m.nodes.append(node("a"))
    m.flows.append(m.flows[0])
    m.lanes.append(m.lanes[0])
    errs = [e for e in validate(m) if e.code == "DUPLICATE_ID"]
    assert len(errs) == 3 and errs[1].node_ids == ["a"]


def test_invalid_lane() -> None:
    m = linear(node("a", lane="ghost"))
    assert codes(m) == ["INVALID_LANE"]
    assert validate(m)[0].node_ids == ["a"]


def test_dangling_flow() -> None:
    m = linear(node("a"))
    m.flows.append(flow("a", "nowhere"))
    errs = validate(m)
    assert [e.code for e in errs] == ["DANGLING_FLOW"] and errs[0].node_ids == ["nowhere"]


def test_no_start_and_no_end() -> None:
    m = model([node("a"), node("b")], [flow("a", "b")])
    assert codes(m) == ["NO_END_EVENT", "NO_START_EVENT"]


def test_multiple_starts_only_allowed_one_per_lane() -> None:
    same_lane = linear(node("a"))
    same_lane.nodes.append(node("start2", "start_event"))
    same_lane.flows.append(flow("start2", "a"))
    assert codes(same_lane) == ["MULTIPLE_START_EVENTS"]

    per_lane = model(
        [node("s1", "start_event"), node("s2", "start_event", lane="l2"), node("a"), node("end", "end_event")],
        [flow("s1", "a"), flow("s2", "a"), flow("a", "end")],
        lanes=["l1", "l2"],
    )
    assert validate(per_lane) == []


def test_orphan_node() -> None:
    m = linear(node("a"))
    m.nodes.append(node("lonely"))
    assert codes(m) == ["ORPHAN_NODE"]  # not also reported as unreachable / dead end


def test_unreachable_and_dead_end() -> None:
    m = linear(node("a"))
    m.nodes += [node("island1"), node("island2")]
    m.flows.append(flow("island1", "island2"))
    errs = validate(m)
    assert sorted((e.code, e.node_ids[0]) for e in errs) == [
        ("DEAD_END", "island1"),
        ("DEAD_END", "island2"),
        ("UNREACHABLE", "island1"),
        ("UNREACHABLE", "island2"),
    ]


def test_gateway_without_branches() -> None:
    assert codes(linear(node("g", "parallel_gateway"))) == ["GATEWAY_NO_BRANCH"]


def test_join_gateway_is_fine() -> None:
    m = model(
        [
            node("start", "start_event"),
            node("split", "parallel_gateway"),
            node("a"),
            node("b"),
            node("join", "parallel_gateway"),
            node("end", "end_event"),
        ],
        [
            flow("start", "split"),
            flow("split", "a"),
            flow("split", "b"),
            flow("a", "join"),
            flow("b", "join"),
            flow("join", "end"),
        ],
    )
    assert validate(m) == []


def test_exclusive_split_needs_conditions() -> None:
    m = model(
        [node("start", "start_event"), node("g", "exclusive_gateway"), node("a"), node("b"), node("end", "end_event")],
        [flow("start", "g"), flow("g", "a", "Yes"), flow("g", "b", "  "), flow("a", "end"), flow("b", "end")],
    )
    errs = validate(m)
    assert [e.code for e in errs] == ["MISSING_CONDITION"] and errs[0].node_ids == ["g", "b"]
    # Parallel splits don't need conditions.
    m.nodes[1].type = "parallel_gateway"
    assert validate(m) == []


def test_broken_fixture_reports_each_problem() -> None:
    assert codes(ProcessModel.model_validate_json(BROKEN.read_text())) == [
        "DANGLING_FLOW",  # t_pay -> t_archive
        "DUPLICATE_ID",  # t_ap twice
        "INVALID_LANE",  # lane_finance
        "MISSING_CONDITION",  # g_amount -> t_fin
        "NO_END_EVENT",
        "ORPHAN_NODE",  # t_file
    ]


class ScriptedLLM(LLMProvider):
    """Returns the scripted responses in order; an Exception instance is raised instead."""

    def __init__(self, *responses: BaseModel | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def structured(
        self, prompt: str, input: str, schema: type[T], model_role: ModelRole, metadata: dict[str, Any] | None = None
    ) -> T:
        self.calls.append({"role": model_role, "input": input, "metadata": metadata})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return schema.model_validate(r.model_dump())


def test_valid_model_skips_repair() -> None:
    llm = ScriptedLLM()
    result = repair(llm, gold_model("01_invoice_approval"), SEGMENTS)
    assert result.repair_attempts == 0 and result.unresolved_errors == [] and llm.calls == []


def test_broken_extraction_is_repaired() -> None:
    broken = ProcessModel.model_validate_json(BROKEN.read_text())
    fixed = gold_model("01_invoice_approval")
    llm = ScriptedLLM(fixed)
    result = repair(llm, broken, SEGMENTS)

    assert result.repair_attempts == 1 and result.unresolved_errors == []
    assert result.model.name == fixed.name
    call = llm.calls[0]
    assert call["role"] == "repair" and "MISSING_CONDITION" in call["input"] and "[s2] Priya:" in call["input"]
    assert call["metadata"]["repair_attempt"] == 1 and "NO_END_EVENT" in call["metadata"]["error_codes"]


def test_unrepairable_extraction_degrades_to_open_questions() -> None:
    broken = ProcessModel.model_validate_json(BROKEN.read_text())
    partly = broken.model_copy(deep=True)
    partly.nodes = [n for n in partly.nodes if n.id != "t_file"]  # fixes ORPHAN_NODE only
    llm = ScriptedLLM(RuntimeError("provider timeout"), partly)

    result = repair(llm, broken, SEGMENTS)

    assert result.repair_attempts == MAX_REPAIR_ATTEMPTS
    assert len(result.unresolved_errors) == 5  # best version kept: the partial fix
    assert "t_file" not in {n.id for n in result.model.nodes}
    questions = [q for q in result.model.open_questions if q.id.startswith("validation_")]
    assert len(questions) == 5 and all(q.question.startswith("Needs review (") for q in questions)
    cond_q = next(q for q in questions if "MISSING_CONDITION" in q.question)
    assert cond_q.related_node_ids == ["g_amount", "t_fin"] and cond_q.source_segment_ids == ["s2"]
    validate_xsd(to_bpmn(result.model))  # still converts to valid BPMN


@pytest.mark.parametrize("bad", [RuntimeError("down"), ValueError("schema")])
def test_repair_llm_failures_never_raise(bad: Exception) -> None:
    broken = ProcessModel.model_validate_json(BROKEN.read_text())
    result = repair(ScriptedLLM(bad, bad), broken, SEGMENTS)
    assert result.repair_attempts == 2 and len(result.unresolved_errors) == 6
