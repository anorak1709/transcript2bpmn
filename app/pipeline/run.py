"""The full pipeline: file bytes -> segments -> ProcessModel -> BPMN XML."""

from pathlib import Path

from app.llm.provider import LiteLLMProvider, LLMProvider
from app.models.process import ProcessModel
from app.models.transcript import Segment
from app.pipeline import convert, extract, ingest, normalize


def transcript_to_model(filename: str, data: bytes, llm: LLMProvider) -> tuple[list[Segment], ProcessModel]:
    segments = normalize.normalize(ingest.parse(filename, data))
    return segments, extract.extract(llm, segments)


def model_to_bpmn(model: ProcessModel) -> str:
    xml = convert.to_bpmn(model)
    convert.validate_xsd(xml)
    return xml.decode()


def eval_pipeline(transcript: Path) -> ProcessModel:
    """Entry point for eval/run_eval.py. Uses the env-configured LLM."""
    _, model = transcript_to_model(transcript.name, transcript.read_bytes(), LiteLLMProvider())
    return model
