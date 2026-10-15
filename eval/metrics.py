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


def assign(weights: list[list[float]]) -> dict[int, int]:
    """Maximum-weight one-to-one assignment (Hungarian algorithm, O(n^3)). Returns
    {row: col} for pairs with positive weight; zero means "not allowed to pair"."""
    if not weights or not weights[0]:
        return {}
    flip = len(weights) > len(weights[0])
    w = [list(r) for r in zip(*weights, strict=True)] if flip else weights
    n, m = len(w), len(w[0])
    inf = float("inf")
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = -w[i0 - 1][j - 1] - u[i0] - v[j]  # minimize negative weight
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0], j0 = p[j1], j1
    pairs = {p[j] - 1: j - 1 for j in range(1, m + 1) if p[j] and w[p[j] - 1][j - 1] > 0}
    return {c: r for r, c in pairs.items()} if flip else pairs


def match_nodes(pred: ProcessModel, gold: ProcessModel, threshold: float) -> dict[str, str]:
    """Return {pred_node_id: gold_node_id}: the one-to-one matching with the highest total
    name similarity among allowed pairs (same kind; tasks and gateways must also clear the
    threshold; events match on type alone since their names vary wildly)."""

    def weight(p: Node, g: Node) -> float:
        if _kind(p) != _kind(g):
            return 0.0
        sim = similarity(p.name, g.name)
        allowed = p.type in ("start_event", "end_event") or sim >= threshold
        return 1.0 + sim if allowed else 0.0  # +1: any allowed match beats leaving both unmatched

    pairs = assign([[weight(p, g) for g in gold.nodes] for p in pred.nodes])
    return {pred.nodes[r].id: gold.nodes[c].id for r, c in pairs.items()}


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
        similarity(pred_lane.get(p.lane_id, ""), gold_lane.get(g.lane_id, "")) >= threshold for p, g in matched_tasks
    )

    gold_gateways = [n for n in gold.nodes if n.type in GATEWAY_TYPES]
    gateway_hits = sum(1 for pid, gid in mapping.items() if pred_by_id[pid].type in GATEWAY_TYPES)

    gold_edges = {(f.source_id, f.target_id) for f in gold.flows}
    pred_edges = {
        (mapping.get(f.source_id, f"?{f.source_id}"), mapping.get(f.target_id, f"?{f.target_id}")) for f in pred.flows
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
