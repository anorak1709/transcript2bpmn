"""Multi-meeting merge eval.

Case layout (eval/gold_merge/<case>/):
    transcript_1.vtt|txt, transcript_2.txt, ...   meetings, merged in order
    model_1.json, model_2.json, ...                gold single-meeting extractions
    expected.json                                  gold merged ProcessModel
    meta.yaml                                      meeting_type, notes, expected_conflicts: [{kind, node}]

Metrics, on top of the single-map ones (eval/metrics.py) against expected.json:
- duplicate_task_rate: share of merged tasks that duplicate another merged task (several map
  to the same gold task). 0 is perfect.
- conflict_recall: share of expected conflicts reported with the right kind on the right step.

Pipelines:
    app.pipeline.run:merge_eval_pipeline       real: LLM extraction of each transcript + merge
    eval.merge_eval:gold_extraction_pipeline   merge only: gold model_N.json + real merge (LLM embeddings)

    python -m eval.merge_eval --pipeline eval.merge_eval:gold_extraction_pipeline
"""

import argparse
import json
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from app.llm.provider import LiteLLMProvider, LLMProvider
from app.models.process import TASK_TYPES, ProcessModel
from app.pipeline.merge import ConflictDraft, merge, qualify
from eval.metrics import Matcher, lexical_matcher, match_nodes, score, similarity
from eval.run_eval import load_pipeline, make_matcher

MergePipeline = Callable[[list[Path]], tuple[ProcessModel, list[ConflictDraft]]]
METRICS = ("task_recall", "task_precision", "lane_accuracy", "flow_edge_f1", "duplicate_task_rate", "conflict_recall")


def merge_models(llm: LLMProvider, models: list[ProcessModel]) -> tuple[ProcessModel, list[ConflictDraft]]:
    merged = qualify(models[0], "T1")
    conflicts: list[ConflictDraft] = []
    for k, m in enumerate(models[1:], 2):
        result = merge(llm, merged, qualify(m, f"T{k}"), f"T{k}")
        merged, conflicts = result.model, conflicts + result.conflicts
    return merged, conflicts


def gold_extraction_pipeline(
    transcripts: list[Path], llm: LLMProvider | None = None
) -> tuple[ProcessModel, list[ConflictDraft]]:
    models = [
        ProcessModel.model_validate_json(p.with_name(f"model_{k}.json").read_text())
        for k, p in enumerate(transcripts, 1)
    ]
    return merge_models(llm or LiteLLMProvider(), models)


# ponytail: duplicates stay lexical (a one-to-one matcher can't show two steps hitting one gold
# step); paraphrased duplicates are undercounted. Upgrade: many-to-one semantic matching.
def duplicate_task_rate(pred: ProcessModel, gold: ProcessModel, threshold: float) -> float:
    gold_tasks = [g for g in gold.nodes if g.type in TASK_TYPES]
    pred_tasks = [p for p in pred.nodes if p.type in TASK_TYPES]
    hits: Counter[str] = Counter()
    for p in pred_tasks:
        best = max(gold_tasks, key=lambda g: similarity(p.name, g.name), default=None)
        if best is not None and similarity(p.name, best.name) >= threshold:
            hits[best.id] += 1
    return sum(c - 1 for c in hits.values()) / len(pred_tasks) if pred_tasks else 0.0


def conflict_recall(
    pred: ProcessModel,
    conflicts: list[ConflictDraft],
    expected: list[dict[str, str]],
    threshold: float,
    gold_names: dict[str, str] | None = None,
) -> float:
    """`gold_names` {pred_id: matched gold step's name}: lets a conflict on a paraphrased step
    count, since `expected` names the gold step."""
    if not expected:
        return 1.0
    names = {n.id: n.name for n in pred.nodes}
    gold_names = gold_names or {}

    def hit(nid: str, want: str) -> bool:
        return any(similarity(x, want) >= threshold for x in (names.get(nid, ""), gold_names.get(nid, "")))

    found = sum(
        any(c.kind == e["kind"] and any(hit(nid, e["node"]) for nid in c.node_ids) for c in conflicts) for e in expected
    )
    return found / len(expected)


def run(
    pipeline: MergePipeline, gold_dir: Path, threshold: float = 0.8, matcher: Matcher | None = None
) -> dict[str, Any]:
    matcher = matcher or lexical_matcher(threshold)
    cases = []
    for case_dir in sorted(p for p in gold_dir.iterdir() if p.is_dir()):
        meta = yaml.safe_load((case_dir / "meta.yaml").read_text()) or {}
        case: dict[str, Any] = {"case": case_dir.name, "meeting_type": meta.get("meeting_type")}
        try:
            transcripts = sorted(case_dir.glob("transcript_*.*"), key=lambda p: int(p.stem.split("_")[1]))
            gold = ProcessModel.model_validate_json((case_dir / "expected.json").read_text())
            pred, conflicts = pipeline(transcripts)
            mapping = match_nodes(pred, gold, matcher)
            gold_by_id = {n.id: n.name for n in gold.nodes}
            m = score(pred, gold, threshold, matcher, mapping)
            m.pop("gateway_recall")
            m["duplicate_task_rate"] = duplicate_task_rate(pred, gold, threshold)
            m["conflict_recall"] = conflict_recall(
                pred, conflicts, meta.get("expected_conflicts") or [], threshold,
                {p: gold_by_id[g] for p, g in mapping.items()},
            )  # fmt: skip
            case["metrics"] = m
            case["conflicts"] = [f"{c.kind}: {c.description}" for c in conflicts]
        except Exception as e:  # report and keep going
            case["error"] = f"{type(e).__name__}: {e}"
        cases.append(case)
    ok = [c["metrics"] for c in cases if "metrics" in c]
    return {"cases": cases, "aggregate": {k: mean(c[k] for c in ok) for k in METRICS} if ok else {}}


def to_markdown(results: dict[str, Any], title: str) -> str:
    lines = [f"# Merge eval: {title}", "", "| case | " + " | ".join(METRICS) + " |", "|---" * (len(METRICS) + 1) + "|"]
    for c in results["cases"]:
        cells = [f"{c['metrics'][m]:.2f}" for m in METRICS] if "metrics" in c else ["ERROR"] * len(METRICS)
        lines.append(f"| {c['case']} | " + " | ".join(cells) + " |")
    if results["aggregate"]:
        lines.append("| **mean** | " + " | ".join(f"**{results['aggregate'][m]:.2f}**" for m in METRICS) + " |")
    for c in results["cases"]:
        lines += (
            ["", f"## {c['case']}"]
            + [f"- {x}" for x in c.get("conflicts", [])]
            + ([f"- ERROR {c['error']}"] if "error" in c else [])
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", default="app.pipeline.run:merge_eval_pipeline")
    ap.add_argument("--gold", type=Path, default=Path("eval/gold_merge"))
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--out", type=Path, default=Path("eval/reports/merge"))
    ap.add_argument("--match", choices=("semantic", "lexical"), default="semantic", help="semantic needs an LLM")
    args = ap.parse_args()
    matcher = make_matcher(args.match, args.threshold)
    results = run(load_pipeline(args.pipeline), args.gold, args.threshold, matcher)  # type: ignore[arg-type]
    args.out.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("%Y%m%d-%H%M%S")
    (args.out / f"{stem}.json").write_text(json.dumps(results, indent=2))
    md = to_markdown(results, f"{args.pipeline} @ {stem}")
    (args.out / f"{stem}.md").write_text(md)
    print(md + f"\nReport: {args.out / stem}.md")


if __name__ == "__main__":
    main()
