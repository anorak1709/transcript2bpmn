"""Compare a predicted ProcessModel to a gold one.

Nodes are matched one-to-one within the same kind (task / gateway type / event type),
greedily by name similarity. Every other metric is computed through that matching.
"""

from difflib import SequenceMatcher

from app.models.process import GATEWAY_TYPES, TASK_TYPES, Node, ProcessModel


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _kind(node: Node) -> str:
    return "task" if node.type in TASK_TYPES else node.type


def _ratio(num: int, den: int) -> float:
    return num / den if den else 1.0  # nothing expected and nothing produced counts as perfect


def match_nodes(pred: ProcessModel, gold: ProcessModel, threshold: float) -> dict[str, str]:
    """Return {pred_node_id: gold_node_id}.

    Events match on type alone (their names vary wildly and carry little signal);
    tasks and gateways must also clear the name-similarity threshold.
    """
    # ponytail: greedy, not Hungarian. Fine for tens of nodes; swap in scipy's
    # linear_sum_assignment if near-tie mismatches show up in reports.
    candidates: list[tuple[float, str, str]] = []
    for p in pred.nodes:
        for g in gold.nodes:
            if _kind(p) != _kind(g):
                continue
            score = similarity(p.name, g.name)
            is_event = p.type in ("start_event", "end_event")
            if is_event or score >= threshold:
                candidates.append((score, p.id, g.id))
    candidates.sort(reverse=True)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for _, pid, gid in candidates:
        if pid not in mapping and gid not in used:
            mapping[pid] = gid
            used.add(gid)
    return mapping


def score(pred: ProcessModel, gold: ProcessModel, threshold: float = 0.8) -> dict[str, float]:
    mapping = match_nodes(pred, gold, threshold)
    pred_by_id = {n.id: n for n in pred.nodes}
    gold_by_id = {n.id: n for n in gold.nodes}

    pred_tasks = [n for n in pred.nodes if n.type in TASK_TYPES]
    gold_tasks = [n for n in gold.nodes if n.type in TASK_TYPES]
    matched_tasks = [(p, gold_by_id[mapping[p.id]]) for p in pred_tasks if p.id in mapping]

    pred_lane = {lane.id: lane.name for lane in pred.lanes}
    gold_lane = {lane.id: lane.name for lane in gold.lanes}
    lane_hits = sum(
        similarity(pred_lane.get(p.lane_id, ""), gold_lane.get(g.lane_id, "")) >= threshold
        for p, g in matched_tasks
    )

    gold_gateways = [n for n in gold.nodes if n.type in GATEWAY_TYPES]
    gateway_hits = sum(1 for pid, gid in mapping.items() if pred_by_id[pid].type in GATEWAY_TYPES)

    gold_edges = {(f.source_id, f.target_id) for f in gold.flows}
    pred_edges = {
        (mapping.get(f.source_id, f"?{f.source_id}"), mapping.get(f.target_id, f"?{f.target_id}"))
        for f in pred.flows
    }
    edge_hits = len(gold_edges & pred_edges)
    edge_p = _ratio(edge_hits, len(pred_edges))
    edge_r = _ratio(edge_hits, len(gold_edges))

    return {
        "task_recall": _ratio(len(matched_tasks), len(gold_tasks)),
        "task_precision": _ratio(len(matched_tasks), len(pred_tasks)),
        "lane_accuracy": _ratio(lane_hits, len(matched_tasks)),
        "gateway_recall": _ratio(gateway_hits, len(gold_gateways)),
        "flow_edge_f1": 2 * edge_p * edge_r / (edge_p + edge_r) if edge_p + edge_r else 0.0,
    }
