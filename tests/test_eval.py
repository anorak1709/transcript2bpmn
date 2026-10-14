import json
from pathlib import Path

from app.models.process import ProcessModel
from eval.metrics import score
from eval.run_eval import run_eval, write_report
from eval.stub_pipeline import pipeline as oracle

GOLD = Path(__file__).parent.parent / "eval" / "gold"


def _gold(case: str) -> ProcessModel:
    return ProcessModel.model_validate_json((GOLD / case / "expected.json").read_text())


def test_perfect_prediction_scores_one() -> None:
    gold = _gold("01_invoice_approval")
    assert set(score(gold, gold).values()) == {1.0}


def test_imperfect_prediction() -> None:
    gold = _gold("02_employee_onboarding")  # 4 tasks, 2 gateways, 8 flows
    pred = gold.model_copy(deep=True)
    # Drop the orientation task and rewire join -> end.
    pred.nodes = [n for n in pred.nodes if n.id != "t_orient"]
    pred.flows = [f for f in pred.flows if "t_orient" not in (f.source_id, f.target_id)]
    rewire = {"id": "fx", "source_id": "g_join", "target_id": "end"}
    pred.flows.append(pred.flows[0].model_copy(update=rewire))
    # Different ids + slightly different wording must still match.
    for n in pred.nodes:
        n.id = "p_" + n.id
    for f in pred.flows:
        f.source_id, f.target_id = "p_" + f.source_id, "p_" + f.target_id
    pred.nodes[1].name = "Create the employee record in Workday"
    # Put IT's task in the wrong lane.
    next(n for n in pred.nodes if n.id == "p_t_laptop").lane_id = "lane_hr"

    s = score(pred, gold)
    assert s["task_recall"] == 3 / 4
    assert s["task_precision"] == 1.0
    assert s["lane_accuracy"] == 2 / 3
    assert s["gateway_recall"] == 1.0
    # 6 of 7 predicted edges are gold; 6 of 8 gold edges found.
    p, r = 6 / 7, 6 / 8
    assert abs(s["flow_edge_f1"] - 2 * p * r / (p + r)) < 1e-9


def test_threshold_is_configurable() -> None:
    gold = _gold("01_invoice_approval")
    pred = gold.model_copy(deep=True)
    next(n for n in pred.nodes if n.id == "t_enter").name = "Key invoice into ERP system"
    assert score(pred, gold, threshold=0.5)["task_recall"] == 1.0
    assert score(pred, gold, threshold=0.95)["task_recall"] < 1.0


def test_run_eval_writes_reports(tmp_path: Path) -> None:
    results = run_eval(oracle, GOLD)
    assert results["failed"] == 0 and len(results["cases"]) >= 2
    md = write_report(results, tmp_path, "oracle")
    assert "| **mean / total** |" in md.read_text()
    assert json.loads(md.with_suffix(".json").read_text())["aggregate"]["task_recall"] == 1.0


def test_failing_case_is_reported_not_raised() -> None:
    def broken(_: Path) -> ProcessModel:
        raise RuntimeError("boom")

    results = run_eval(broken, GOLD)
    assert results["failed"] == len(results["cases"])
    assert "boom" in results["cases"][0]["error"]
