"""Run a pipeline over the gold set and write a timestamped markdown + JSON report.

Gold case layout (one folder per case):
    transcript.vtt | transcript.txt
    expected.json   # ProcessModel
    meta.yaml       # meeting_type: walkthrough | general, notes: ...

Usage:
    python -m eval.run_eval --gold eval/gold                                   # real pipeline
    python -m eval.run_eval --pipeline eval.stub_pipeline:pipeline            # oracle stub
"""

import argparse
import importlib
import json
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from app.models.process import ProcessModel
from app.pipeline.validate import RepairResult
from eval.metrics import score

# A pipeline may return a bare model (stubs) or a RepairResult (real pipeline, adds repair stats).
Pipeline = Callable[[Path], ProcessModel | RepairResult]
METRICS = ("task_recall", "task_precision", "lane_accuracy", "gateway_recall", "flow_edge_f1")


def transcript_path(case_dir: Path) -> Path:
    for name in ("transcript.vtt", "transcript.txt"):
        if (case_dir / name).exists():
            return case_dir / name
    raise FileNotFoundError(f"{case_dir}: no transcript.vtt or transcript.txt")


def run_eval(pipeline: Pipeline, gold_dir: Path, threshold: float = 0.8) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for case_dir in sorted(p for p in gold_dir.iterdir() if p.is_dir()):
        meta = yaml.safe_load((case_dir / "meta.yaml").read_text()) or {}
        case: dict[str, Any] = {"case": case_dir.name, "meeting_type": meta.get("meeting_type")}
        try:
            gold = ProcessModel.model_validate_json((case_dir / "expected.json").read_text())
            out = pipeline(transcript_path(case_dir))
            model = out.model if isinstance(out, RepairResult) else out
            case["metrics"] = score(model, gold, threshold)
            if isinstance(out, RepairResult):
                case["repair_attempts"] = out.repair_attempts
                case["unresolved_errors"] = [f"{e.code}: {e.message}" for e in out.unresolved_errors]
        except Exception:
            # One bad case must not sink the whole run; it's reported instead.
            case["error"] = traceback.format_exc()
        cases.append(case)

    ok = [c["metrics"] for c in cases if "metrics" in c]
    return {
        "threshold": threshold,
        "cases": cases,
        "aggregate": {m: mean(c[m] for c in ok) for m in METRICS} if ok else {},
        "failed": sum("error" in c for c in cases),
        "repair_attempts": sum(c.get("repair_attempts", 0) for c in cases),
        "unresolved_errors": sum(len(c.get("unresolved_errors", [])) for c in cases),
    }


def to_markdown(results: dict[str, Any], title: str) -> str:
    lines = [f"# Eval report: {title}", "", f"Fuzzy-match threshold: {results['threshold']}", ""]
    extra = ("repair attempts", "unresolved errors")
    lines += ["| case | type | " + " | ".join(METRICS + extra) + " |", "|---" * (len(METRICS) + 4) + "|"]
    for c in results["cases"]:
        cells = [f"{c['metrics'][m]:.2f}" for m in METRICS] if "metrics" in c else ["ERROR"] * len(METRICS)
        cells += [
            str(c.get("repair_attempts", "-")),
            str(len(c["unresolved_errors"])) if "unresolved_errors" in c else "-",
        ]
        lines.append(f"| {c['case']} | {c['meeting_type']} | " + " | ".join(cells) + " |")
    if results["aggregate"]:
        agg = [f"**{results['aggregate'][m]:.2f}**" for m in METRICS]
        totals = [f"**{results['repair_attempts']}**", f"**{results['unresolved_errors']}**"]
        lines.append("| **mean / total** | | " + " | ".join(agg + totals) + " |")
    lines += ["", f"Failed cases: {results['failed']}"]
    for c in results["cases"]:
        if c.get("unresolved_errors"):
            lines += ["", f"## {c['case']} unresolved validation errors"] + [f"- {e}" for e in c["unresolved_errors"]]
    for c in results["cases"]:
        if "error" in c:
            lines += ["", f"## {c['case']} error", "```", c["error"].rstrip(), "```"]
    return "\n".join(lines) + "\n"


def write_report(results: dict[str, Any], out_dir: Path, label: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("%Y%m%d-%H%M%S")
    results = {**results, "pipeline": label, "timestamp": stem}
    (out_dir / f"{stem}.json").write_text(json.dumps(results, indent=2))
    md = out_dir / f"{stem}.md"
    md.write_text(to_markdown(results, f"{label} @ {stem}"))
    return md


def load_pipeline(spec: str) -> Pipeline:
    module, _, attr = spec.partition(":")
    fn: Pipeline = getattr(importlib.import_module(module), attr)
    return fn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", default="app.pipeline.run:eval_pipeline", help="module:function")
    ap.add_argument("--gold", type=Path, default=Path("eval/gold"))
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--out", type=Path, default=Path("eval/reports"))
    args = ap.parse_args()

    results = run_eval(load_pipeline(args.pipeline), args.gold, args.threshold)
    report = write_report(results, args.out, args.pipeline)
    print(report.read_text())
    print(f"Report: {report}")


if __name__ == "__main__":
    main()
