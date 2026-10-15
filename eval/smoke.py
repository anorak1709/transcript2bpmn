"""Live smoke test of the whole pipeline against the configured provider (no fakes).

Proves a provider switch (e.g. OpenAI -> Azure OpenAI) works end to end with config only:
    LLM_PROVIDER=azure LLM_API_BASE=... LLM_API_VERSION=... MODEL_*=<deployments> \
        uv run python -m eval.smoke [--audio eval/asr/samples/invoice_approval.m4a]

Exercises every model role: filter + extract (each meeting), repair (if needed), embed + merge
(combining the two meetings), and transcription with --audio. Output must be valid BPMN.
Exit code 0 = all checks passed. Needs no database or object storage.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.llm.provider import LiteLLMProvider
from app.models.process import ProcessModel
from app.pipeline import ingest
from app.pipeline.convert import to_bpmn, validate_xsd
from app.pipeline.export import sop_markdown
from app.pipeline.merge import merge, qualify
from app.pipeline.run import model_from_segments, prepare_segments
from app.pipeline.transcribe import get_transcriber
from app.pipeline.validate import validate

CASE = Path(__file__).parent / "gold_merge" / "01_invoice_two_meetings"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, help="also transcribe this file (needs TRANSCRIBE_MODEL)")
    args = ap.parse_args()
    s = get_settings()
    print(
        f"provider={s.llm_provider} base={s.llm_api_base or '(default)'} "
        f"models: extract={s.model_extract} filter={s.model_filter} repair={s.model_repair} "
        f"merge={s.model_merge} embed={s.model_embed}"
    )
    llm = LiteLLMProvider(s)
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}")
        if not ok:
            failures.append(name)

    try:
        models: list[ProcessModel] = []
        segs_by_t: dict[str, dict[str, Any]] = {}
        for k, path in enumerate(sorted(CASE.glob("transcript_*.*")), 1):
            t0 = time.time()
            segments = prepare_segments(ingest.parse(path.name, path.read_bytes()), llm)
            result = model_from_segments(segments, llm)
            tasks = [n.name for n in result.model.nodes if n.type.endswith("task")]
            check(
                f"extract meeting {k}",
                bool(tasks),
                f"{len(tasks)} tasks, {result.repair_attempts} repair "
                f"attempt(s), {len(result.unresolved_errors)} unresolved, {time.time() - t0:.1f}s",
            )
            models.append(qualify(result.model, f"T{k}"))
            segs_by_t |= {f"T{k}:{x.segment_id}": x.model_dump() for x in segments}

        merged = merge(llm, models[0], models[1], "T2")
        check(
            "embed + merge",
            True,
            f"{len(merged.node_map)} matched/added, {len(merged.conflicts)} conflict(s): "
            + "; ".join(c.kind for c in merged.conflicts),
        )
        xml = to_bpmn(merged.model)
        validate_xsd(xml)
        check("BPMN XSD", True, f"{len(xml)} bytes, {len(validate(merged.model))} validation issue(s)")
        check("SOP", "## Procedure" in sop_markdown(merged.model, segs_by_t, {"T1": "meeting 1", "T2": "meeting 2"}))

        if args.audio:
            t0 = time.time()
            tr = get_transcriber(s).transcribe(args.audio)
            check(
                "transcribe",
                bool(tr.segments),
                f"{len(tr.segments)} segments, diarized={tr.diarization_available}, {time.time() - t0:.1f}s",
            )
    except Exception as e:  # report, don't traceback-dump secrets
        check("pipeline", False, f"{type(e).__name__}: {str(e)[:300]}")

    print("SMOKE " + ("PASSED" if not failures else f"FAILED: {', '.join(failures)}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
