"""The next meeting's agenda: every open disagreement, policy difference, gap and open question
turned into a question, addressed to the people who described that part of the process.

Template-built (no LLM): free, instant, and says exactly what the map says.
"""

from collections import defaultdict
from datetime import date

from app.db.models import Conflict
from app.insights import Quote, Side, owner_side, people
from app.models.process import ProcessModel
from app.pipeline.gaps import Gap

EVERYONE = "Everyone"


def _who(quotes: list[Quote]) -> str:
    names = people(quotes)
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 2 else names) or EVERYONE


def _conflict_question(c: Conflict, ss: list[Side], names: dict[str, str]) -> str:
    o = c.options
    if c.kind == "missing_step":
        return f"{c.description} Is it still done, and by whom?"
    if c.kind == "unofficial_step":
        return f"{c.description} Is it a required step, or a local habit?"
    if c.kind == "owner":
        q = f"Who does '{names.get(c.node_ids[0], c.node_ids[0])}': {o[0]} or {o[1]}?"
    elif c.kind == "condition":
        u, v = (names.get(i, i) for i in c.node_ids)
        q = f"At '{u}', when does it go to '{v}': \"{o[0]}\" or \"{o[1]}\"?"
    elif c.kind == "order":
        q = f"Which comes first: {o[0].removesuffix(' first')} or {o[1].removesuffix(' first')}?"
    else:  # sequence
        q = (
            f"After '{names.get(c.node_ids[0], c.node_ids[0])}', what comes next: "
            + ", ".join(f"'{x}'" for x in o)
            + "?"
        )
    if c.origin == "policy":  # the map's side cites everyone who described the step, not just one view
        said = [f"the map currently says {ss[0].label}", f"the policy says {ss[1].label}"] if len(ss) == 2 else []
    else:
        said = [f"{', '.join(people(s.quotes))} said {s.label}" for s in ss if people(s.quotes)]
    if said and len(ss) == len(o):
        q += " (" + "; ".join(said) + ".)"
    owner = owner_side(ss)
    if owner is not None:
        q += f" The process owner's account is {ss[owner].label}."
    if c.kind in ("owner", "condition"):
        q += " Or does it depend on the case (region, size, type)?"
    if c.origin == "policy":
        q = "The policy and the meetings differ. " + q
    return q


def build_agenda(
    process: str,
    conflicts: list[tuple[Conflict, list[Side]]],
    gaps: list[Gap],
    model: ProcessModel | None,
    index: dict[str, Quote],
    today: date | None = None,
) -> str:
    names = {n.id: n.name for n in model.nodes} if model else {}
    lanes = {x.id: x.name for x in model.lanes} if model else {}
    node_lane = {n.id: lanes.get(n.lane_id, "") for n in model.nodes} if model else {}
    cites = {n.id: n.source_segment_ids for n in model.nodes} if model else {}

    items: dict[str, list[str]] = defaultdict(list)
    # The same ids the app shows: D1… disagreements, P1… policy differences, G1… gaps.
    point = policy_no = 0
    for c, ss in conflicts:
        if c.origin == "policy":
            policy_no += 1
            ref = f"P{policy_no}"
        else:
            point += 1
            ref = f"D{point}"
        who = _who([q for s in ss for q in s.quotes])
        items[who].append(f"{_conflict_question(c, ss, names)} _({ref})_")

    for k, g in enumerate(gaps, 1):
        quotes = [index[s] for nid in g.node_ids for s in cites.get(nid, []) if s in index]
        who = _who(quotes)
        if who == EVERYONE and node_lane.get(g.node_ids[0]):
            who = f"Whoever leads {node_lane[g.node_ids[0]]}"
        items[who].append(f"{g.question} _(G{k})_")

    for q in model.open_questions if model else []:
        if q.id.startswith("conflict_"):
            continue  # already listed as a point of disagreement
        items[_who([index[s] for s in q.source_segment_ids if s in index])].append(f"{q.question} _(open question)_")

    total = sum(len(v) for v in items.values())
    lines = [
        f"# Next meeting: {process}",
        "",
        f"_{total} question{'s' if total != 1 else ''} drawn from the process map on "
        f"{(today or date.today()).strftime('%-d %B %Y')}: open points of disagreement, differences from "
        "the policy, gaps nobody covered, and open questions. Each is addressed to the people who "
        "described that part of the process._",
    ]
    if not total:
        return "\n".join([*lines, "", "Nothing open: the meetings agree and no gaps were found."]) + "\n"
    order = sorted(items, key=lambda k: (k == EVERYONE, k.startswith("Whoever"), -len(items[k]), k))
    for who in order:
        lines += ["", f"## For {who}" if who != EVERYONE else "## For everyone", ""]
        lines += [f"{k}. {text}" for k, text in enumerate(items[who], 1)]
    return "\n".join(lines) + "\n"
