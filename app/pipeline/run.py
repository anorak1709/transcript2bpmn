"""The full pipeline: file bytes -> segments -> ProcessModel (validated/repaired) -> BPMN XML."""

from pathlib import Path
from typing import Any

from app.llm.provider import LiteLLMProvider, LLMProvider
from app.models.process import ProcessModel
from app.models.transcript import Segment
from app.pipeline import convert, extract, ingest, normalize, validate


def model_from_segments(segments: list[Segment], llm: LLMProvider) -> validate.RepairResult:
    return validate.repair(llm, extract.extract(llm, segments), segments)


def model_to_bpmn(model: ProcessModel, keep: convert.KeptPositions | None = None) -> str:
    """BPMN XML is always derived from the model; it never goes out without passing the XSD."""
    xml = convert.to_bpmn(model, keep)
    convert.validate_xsd(xml)
    return xml.decode()


def eval_pipeline(transcript: Path) -> validate.RepairResult:
    """Entry point for eval/run_eval.py. Uses the env-configured LLM."""
    segments = normalize.normalize(ingest.parse(transcript.name, transcript.read_bytes()))
    return model_from_segments(segments, LiteLLMProvider())


def merge_eval_pipeline(transcripts: list[Path]) -> tuple[ProcessModel, list[Any]]:
    """Entry point for eval/merge_eval.py: extract every meeting with the LLM, then merge in order."""
    from eval.merge_eval import merge_models

    llm = LiteLLMProvider()
    models = []
    for t in transcripts:
        segments = normalize.normalize(ingest.parse(t.name, t.read_bytes()))
        models.append(model_from_segments(segments, llm).model)
    return merge_models(llm, models)
