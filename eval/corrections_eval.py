"""Do people's corrections still need making? Re-runs extraction (+ merge) on corrected cases
exported by scripts/export_corrections.py and checks each fix against the new output.

    uv run python -m eval.corrections_eval [--cases eval/corrections/local]

A fix counts as learned when the new draft already says what the person changed it to: the
renamed step exists under its new name, a moved step is in its new lane, a deleted step is
gone, an added step is now extracted, a connection exists (or no longer does). Anonymised
cases have no meeting text and are counted but not re-run.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.llm.provider import LiteLLMProvider, LLMProvider
from app.models.process import ProcessModel
from app.models.transcript import Segment
from app.pipeline.run import model_from_segments
from eval.merge_eval import merge_models
from eval.metrics import similarity

THRESHOLD = 0.8


def _draft(llm: LLMProvider, meetings: list[list[dict[str, Any]]]) -> ProcessModel:
    models = [
        model_from_segments(
            [Segment(segment_id=f"s{i}", speaker=x.get("speaker"), start_ts=None, end_ts=None, text=x["text"])
             for i, x in enumerate(lines, 1)],
            llm,
        ).model
        for lines in meetings
    ]  # fmt: skip
    return models[0] if len(models) == 1 else merge_models(llm, models)[0]


def learned(fix: dict[str, Any], m: ProcessModel) -> bool:
    lanes = {x.id: x.name for x in m.lanes}

    def find(name: str) -> list[Any]:
        return [n for n in m.nodes if similarity(n.name, name) >= THRESHOLD]

    a, b = fix.get("after") or {}, fix.get("before") or {}
    kind = fix["kind"]
    if kind in ("rename", "add"):
        return bool(find(a["name"]))
    if kind == "move":
        return any(similarity(lanes.get(n.lane_id, ""), a["lane"]) >= THRESHOLD for n in find(a["name"]))
    if kind == "retype":
        return any(n.type == a["type"] for n in find(a["name"]))
    if kind == "delete":
        return not find(b["name"])
    ids = {n.name: n.id for n in m.nodes}
    edges = {(f.source_id, f.target_id) for f in m.flows}
    pair = a if kind == "connect" else b
    src = [ids[n] for n in ids if similarity(n, pair["from"]) >= THRESHOLD]
    dst = [ids[n] for n in ids if similarity(n, pair["to"]) >= THRESHOLD]
    present = any((s, t) in edges for s in src for t in dst)
    return present if kind == "connect" else not present


def run(cases: list[dict[str, Any]], llm: LLMProvider) -> dict[str, Any]:
    total: Counter[str] = Counter()
    ok: Counter[str] = Counter()
    skipped = 0
    for case in cases:
        if not case.get("meetings"):
            skipped += 1
            continue
        draft = _draft(llm, case["meetings"])
        for fix in case["corrections"]:
            total[fix["kind"]] += 1
            ok[fix["kind"]] += learned(fix, draft)
    rate = {k: ok[k] / total[k] for k in total}
    return {"learned": sum(ok.values()), "fixes": sum(total.values()), "by_kind": rate, "skipped_anonymised": skipped}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=Path("eval/corrections/local"))
    args = ap.parse_args()
    cases = [json.loads(p.read_text()) for p in sorted(args.cases.glob("*.json"))]
    r = run(cases, LiteLLMProvider())
    print(f"{r['learned']}/{r['fixes']} corrections already right in the new draft "
          f"({r['skipped_anonymised']} anonymised case(s) not re-run)")  # fmt: skip
    for k, v in sorted(r["by_kind"].items()):
        print(f"  {k:10} {v:.0%}")


if __name__ == "__main__":
    main()
