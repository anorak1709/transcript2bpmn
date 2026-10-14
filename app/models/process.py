"""Canonical process model. The LLM fills this; deterministic code turns it into BPMN.

Strict-mode compatible: no free-form dicts, every field required, null for empty.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal[
    "start_event",
    "end_event",
    "user_task",
    "service_task",
    "exclusive_gateway",
    "parallel_gateway",
]

TASK_TYPES: frozenset[str] = frozenset({"user_task", "service_task"})
GATEWAY_TYPES: frozenset[str] = frozenset({"exclusive_gateway", "parallel_gateway"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Lane(_Strict):
    id: str
    name: str


class Node(_Strict):
    id: str
    type: NodeType
    name: str
    lane_id: str
    source_segment_ids: list[str]
    confidence: float = Field(ge=0, le=1)


class Flow(_Strict):
    id: str
    source_id: str
    target_id: str
    condition: str | None


class OpenQuestion(_Strict):
    id: str
    question: str
    related_node_ids: list[str]
    source_segment_ids: list[str]


class ProcessModel(_Strict):
    name: str
    lanes: list[Lane]
    nodes: list[Node]
    flows: list[Flow]
    open_questions: list[OpenQuestion]
