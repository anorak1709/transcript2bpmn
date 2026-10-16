"""Merge unit tests (no services): entity resolution, insertion, conflicts, replayable ops."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.models.process import TASK_TYPES, ProcessModel
from app.pipeline.edit import AddExtractedNode, AddOpenQuestion, AddSources, apply_ops
from app.pipeline.merge import PairVerdicts, merge, qualify, resolve
from app.pipeline.validate import validate
from tests.conftest import FakeLLM, gold_model

GOLD_MERGE = Path(__file__).parent.parent / "eval" / "gold_merge"


def load(case: str, k: int) -> ProcessModel:
    return qualify(ProcessModel.model_validate_json((GOLD_MERGE / case / f"model_{k}.json").read_text()), f"T{k}")


def test_qualify_prefixes_citations_once() -> None:
    m = qualify(qualify(gold_model("01_invoice_approval"), "T1"), "T9")
    assert {c for n in m.nodes for c in n.source_segment_ids} <= {"T1:s1", "T1:s2", "T1:s3", "T1:s4"}


def test_invoice_meetings_merge() -> None:
    base, new = load("01_invoice_two_meetings", 1), load("01_invoice_two_meetings", 2)
    llm = FakeLLM(base)
    r = merge(llm, base, new, "T2")

    tasks = [n.name for n in r.model.nodes if n.type in TASK_TYPES]
    assert len(tasks) == len(set(tasks)) == 7
    assert r.model.lanes[-1].name == "Treasury"
    flows = {(f.source_id, f.target_id) for f in r.model.flows}
    assert {("g_join", "t_bank"), ("t_bank", "t_pay")} <= flows and ("g_join", "t_pay") not in flows  # inserted
    assert validate(r.model) == []
    # Existing wording and owners win; the disagreements are surfaced, not applied.
    pay = next(n for n in r.model.nodes if n.id == "t_pay")
    assert (pay.name, pay.lane_id) == ("Pay supplier in weekly payment run", "lane_fin")
    assert "T2:s6" in pay.source_segment_ids
    assert sorted(c.kind for c in r.conflicts) == ["condition", "condition", "owner"]
    assert next(f for f in r.model.flows if f.target_id == "t_fin_approve").condition == "Over $5,000"
    # Ambiguous pairs went to the "merge" LLM in one batch.
    assert [role for role, _ in llm.calls] == ["merge"]


def test_order_conflict_changes_nothing_structural() -> None:
    base, new = load("02_onboarding_order_conflict", 1), load("02_onboarding_order_conflict", 2)
    r = merge(FakeLLM(base), base, new, "T2")
    assert [c.kind for c in r.conflicts] == ["order"]
    assert set(r.conflicts[0].node_ids) == {"t_orient", "t_laptop"}
    assert {(f.source_id, f.target_id) for f in r.model.flows} == {(f.source_id, f.target_id) for f in base.flows}
    q = next(q for q in r.model.open_questions if q.id.startswith("conflict_"))
    assert q.question.startswith("Meetings disagree (order)") and "T2:s2" in q.source_segment_ids


def test_merge_is_a_replayable_op_list() -> None:
    base, new = load("01_invoice_two_meetings", 1), load("01_invoice_two_meetings", 2)
    r = merge(FakeLLM(base), base, new, "T2")
    from pydantic import TypeAdapter

    from app.pipeline.edit import AnyOp

    ops = TypeAdapter(list[AnyOp]).validate_python(json.loads(json.dumps(r.ops)))  # round-trips through JSON (DB)
    assert apply_ops(base, ops) == r.model
    assert {type(o) for o in ops} >= {AddExtractedNode, AddSources, AddOpenQuestion}


def test_merging_a_meeting_into_itself_adds_only_citations() -> None:
    base = load("01_invoice_two_meetings", 1)
    again = qualify(
        ProcessModel.model_validate_json((GOLD_MERGE / "01_invoice_two_meetings" / "model_1.json").read_text()), "T3"
    )
    r = merge(FakeLLM(base), base, again, "T3")
    assert r.conflicts == [] and {o["op"] for o in r.ops} == {"add_sources"}
    assert [n.id for n in r.model.nodes] == [n.id for n in base.nodes]


class Verdicts(FakeLLM):
    def __init__(self, same: bool) -> None:
        super().__init__(gold_model("01_invoice_approval"))
        self.same = same

    def structured(self, prompt: str, input: str, schema: Any, model_role: Any, metadata: Any = None) -> Any:
        self.calls.append((model_role, input))
        assert schema is PairVerdicts
        return PairVerdicts.model_validate(
            {
                "verdicts": [
                    {"pair_id": line.split(" | ")[0], "same": self.same, "reason": ""} for line in input.splitlines()
                ]
            }
        )


@pytest.mark.parametrize("same", [True, False])
def test_resolve_bands(same: bool) -> None:
    base = [("a", "task", "Approve invoice"), ("b", "task", "File receipt")]
    new = [("x", "task", "Approve invoice"), ("y", "task", "File the receipt"), ("z", "task", "Order lunch")]
    llm = Verdicts(same)
    got = resolve(llm, base, new)
    assert got["x"] == "a"  # identical: auto-match, never asked
    assert ("y" in got) is same  # in-between: the LLM decides
    assert "z" not in got  # unrelated: never asked
    asked = llm.calls[0][1]
    assert "File the receipt" in asked and "Order lunch" not in asked and "Approve invoice" not in asked


def test_resolve_never_matches_across_kinds() -> None:
    llm = Verdicts(True)
    assert resolve(llm, [("g", "exclusive_gateway", "Approved?")], [("t", "task", "Approved?")]) == {}
    assert llm.calls == []


def test_merge_eval_metrics() -> None:
    from eval.merge_eval import conflict_recall, duplicate_task_rate, gold_extraction_pipeline, run

    llm = FakeLLM(gold_model("01_invoice_approval"))
    results = run(lambda ts: gold_extraction_pipeline(ts, llm), GOLD_MERGE)
    assert results["aggregate"]["duplicate_task_rate"] == 0 and results["aggregate"]["conflict_recall"] == 1

    gold = gold_model("01_invoice_approval")
    dup = gold.model_copy(deep=True)
    dup.nodes.append(dup.nodes[1].model_copy(update={"id": "t_enter_again", "name": "Enter the invoice into ERP"}))
    assert duplicate_task_rate(dup, gold, 0.8) == 1 / 7  # 7 tasks, one of them a duplicate
    assert conflict_recall(gold, [], [{"kind": "order", "node": "Pay supplier"}], 0.8) == 0


def _apply(kind: str, node_ids: list[str], options: list[str], choice: int, model: ProcessModel) -> ProcessModel:
    from app.pipeline.merge import resolution_ops

    return apply_ops(model, resolution_ops(kind, node_ids, options, choice, model))


def test_resolve_owner_condition_sequence() -> None:
    from app.pipeline.merge import CannotApply, resolution_ops

    m = gold_model("01_invoice_approval")

    def lane(mm: ProcessModel, nid: str) -> str:
        return next(n.lane_id for n in mm.nodes if n.id == nid)

    assert lane(_apply("owner", ["t_pay"], ["Finance", "Accounts Payable"], 1, m), "t_pay") == "lane_ap"
    treasury = _apply("owner", ["t_pay"], ["Finance", "Treasury"], 1, m)
    assert lane(treasury, "t_pay") == "lane_treasury" and treasury.lanes[-1].name == "Treasury"

    cond = _apply("condition", ["g_amount", "t_fin_approve"], ["Over $5,000", "Over $10,000"], 1, m)
    assert next(f.condition for f in cond.flows if f.target_id == "t_fin_approve") == "Over $10,000"
    assert next(n.name for n in cond.nodes if n.id == "g_amount") == "Amount over $10,000?"  # name follows
    # the sibling branch's point then finds the name already updated: no second rename
    both = _apply("condition", ["g_amount", "t_ap_approve"], ["$5,000 or less", "$10,000 or less"], 1, cond)
    assert next(n.name for n in both.nodes if n.id == "g_amount") == "Amount over $10,000?"
    keep = _apply("condition", ["g_amount", "t_fin_approve"], ["Over $5,000", "Over $10,000"], 0, m)
    assert next(n.name for n in keep.nodes if n.id == "g_amount") == "Amount over $5,000?"

    branched = apply_ops(
        m, edit_ops({"op": "connect", "source_id": "t_enter", "target_id": "t_pay", "condition": None})
    )
    seq = _apply("sequence", ["t_enter", "t_match", "t_pay"], ["Match invoice", "Pay supplier"], 0, branched)
    assert [f.target_id for f in seq.flows if f.source_id == "t_enter"] == ["t_match"]

    with pytest.raises(CannotApply):
        resolution_ops("condition", ["g_amount", "t_fin_approve"], ["a", "b"], 5, m)
    with pytest.raises(CannotApply, match="changed or removed"):
        resolution_ops("owner", ["gone"], ["a", "b"], 1, m)


def test_resolve_order_swaps_adjacent_steps_only() -> None:
    from app.pipeline.merge import CannotApply, resolution_ops
    from app.pipeline.validate import validate

    m = gold_model("01_invoice_approval")  # start -> t_enter -> t_match -> g_match ...
    swapped = _apply("order", ["t_match", "t_enter"], ["'Enter' first", "'Match' first"], 1, m)
    edges = {(f.source_id, f.target_id) for f in swapped.flows}
    assert {("start", "t_match"), ("t_match", "t_enter"), ("t_enter", "g_match")} <= edges
    assert ("t_enter", "t_match") not in edges and validate(swapped) == []
    assert _apply("order", ["t_match", "t_enter"], ["keep", "swap"], 0, m) == m  # keep = no change

    onboarding = gold_model("02_employee_onboarding")  # laptop and orientation: a join in between
    with pytest.raises(CannotApply, match="aren't directly next"):
        resolution_ops("order", ["t_orient", "t_laptop"], ["keep", "swap"], 1, onboarding)


def edit_ops(*raw: dict[str, Any]) -> list[Any]:
    from app.pipeline.edit import EditPlan

    return list(EditPlan.model_validate({"ops": list(raw), "reply": ""}).ops)
