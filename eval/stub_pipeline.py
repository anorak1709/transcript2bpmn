"""Oracle stub: returns the gold answer, so `make eval` exercises the harness end to end.

Replaced by the real pipeline in Phase 1.
"""

from pathlib import Path

from app.models.process import ProcessModel


def pipeline(transcript: Path) -> ProcessModel:
    return ProcessModel.model_validate_json((transcript.parent / "expected.json").read_text())
