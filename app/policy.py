"""Compare the merged map (how people say the work is done) with policy/SOP documents.

The policy is a reference, never merged in: its differences are kept as Conflict rows with
origin="policy", listed apart from meeting disagreements. Uses the merge step's matching
(embeddings + the "merge" model for close calls), so a check costs a few cheap LLM calls.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Conflict, Job, ProcessMap, Project, Transcript
from app.llm.provider import LLMProvider
from app.models.process import TASK_TYPES, ProcessModel
from app.pipeline.merge import merge, qualify


def check_policy(db: Session, project: Project, llm: LLMProvider) -> int:
    """Recompute the open policy differences for `project`. Ones the user already settled stay
    settled (matched on kind + description). Returns how many are open."""
    if not project.merged_map_id:
        return 0
    docs = db.scalars(
        select(Transcript).where(Transcript.project_id == project.id, Transcript.purpose == "policy")
    ).all()
    base = ProcessModel.model_validate(db.get_one(ProcessMap, project.merged_map_id).model)
    db.execute(
        delete(Conflict).where(
            Conflict.project_id == project.id, Conflict.origin == "policy", Conflict.status == "open"
        )
    )
    settled = {
        (c.kind, c.description)
        for c in db.scalars(select(Conflict).where(Conflict.project_id == project.id, Conflict.origin == "policy"))
    }
    opened = 0
    for doc in docs:
        job = db.scalars(
            select(Job).where(Job.transcript_id == doc.id, Job.map_id.is_not(None)).order_by(Job.created_at.desc())
        ).first()
        if job is None or job.map_id is None:  # not extracted yet (this check may run mid-job)
            continue
        policy = qualify(ProcessModel.model_validate(db.get_one(ProcessMap, job.map_id).model), doc.id)
        result = merge(llm, base, policy, doc.id, ours="the meetings", theirs="the policy")
        known = {n.id for n in base.nodes}
        # Only differences about steps the map has; a policy-only step is reported once, below.
        drafts = [
            (c.kind, c.description, c.options, c.node_ids, c.sources)
            for c in result.conflicts
            if set(c.node_ids) <= known
        ]

        matched_base = set(result.node_map.values()) & known
        for n in policy.nodes:  # in the policy, never mentioned in a meeting
            if n.type in TASK_TYPES and result.node_map.get(n.id) not in known:
                drafts.append(
                    (
                        "missing_step",
                        f"The policy has '{n.name}', but no meeting mentioned it.",
                        [],
                        [],
                        [
                            {"from": "the meetings", "segment_ids": []},
                            {"from": doc.id, "segment_ids": n.source_segment_ids},
                        ],
                    )
                )
        for n in base.nodes:  # done in practice, not in the policy
            if n.type in TASK_TYPES and n.id not in matched_base and not n.user_added:
                drafts.append(
                    (
                        "unofficial_step",
                        f"'{n.name}' was described in meetings but isn't in the policy.",
                        [],
                        [n.id],
                        [
                            {"from": "the meetings", "segment_ids": n.source_segment_ids},
                            {"from": doc.id, "segment_ids": []},
                        ],
                    )
                )

        for kind, description, options, node_ids, sources in drafts:
            if (kind, description) in settled:
                continue
            settled.add((kind, description))
            db.add(
                Conflict(
                    id=str(uuid.uuid4()),
                    project_id=project.id,
                    origin="policy",
                    kind=kind,
                    description=description,
                    options=options,
                    node_ids=node_ids,
                    sources=sources,
                )
            )
            opened += 1
    return opened
