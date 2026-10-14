from pydantic import BaseModel


class Segment(BaseModel):
    """One utterance. `segment_id` is assigned once by normalize and never changes."""

    segment_id: str
    speaker: str | None
    start_ts: float | None  # seconds
    end_ts: float | None
    text: str
