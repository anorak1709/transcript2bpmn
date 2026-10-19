"""Compare a predicted ProcessModel to a gold one.

Nodes are matched one-to-one within the same kind (task / gateway type / event type).
Every other metric is computed through that matching. Two matchers:
- lexical (default): spelling similarity >= threshold. Strict: "Send invoice back to supplier"
  and "Return invoice to supplier" don't match.
- semantic: by meaning, via the merge step's resolver (embeddings, LLM confirms the close
  calls). Needs an LLM; what the eval CLIs use by default.
"""

from collections.abc import Callable
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from app.models.process import GATEWAY_TYPES, TASK_TYPES, Node, ProcessModel

if TYPE_CHECKING:
    from app.llm.provider import LLMProvider


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


Item = tuple[str, str, str]  # (id, kind, name)
# Matches pred items to gold items one-to-one, equal kinds only: {pred_id: gold_id}
Matcher = Callable[[list[Item], list[Item]], dict[str, str]]


def lexical_matcher(threshold: float) -> Matcher:
    def match(pred: list[Item], gold: list[Item]) -> dict[str, str]:
        def weight(p: Item, g: Item) -> float:
            sim = similarity(p[2], g[2])
            return 1.0 + sim if p[1] == g[1] and sim >= threshold else 0.0  # +1: any match beats none

        pairs = assign([[weight(p, g) for g in gold] for p in pred])
        return {pred[r][0]: gold[c][0] for r, c in pairs.items()}

    return match


def semantic_matcher(llm: "LLMProvider") -> Matcher:
    from app.pipeline.merge import resolve  # the same "is this the same step?" logic merging uses

    return lambda pred, gold: resolve(llm, gold, pred)


def _items(nodes: list[Node]) -> list[Item]:
    return [(n.id, _kind(n), n.name) for n in nodes]


def match_nodes(pred: ProcessModel, gold: ProcessModel, matcher: Matcher) -> dict[str, str]:
    """Return {pred_node_id: gold_node_id}. Tasks and gateways go through the matcher; events
    match on type alone (their names vary wildly), best name similarity first."""
    events = ("start_event", "end_event")
    mapping = matcher(_items([n for n in pred.nodes if n.type not in events]),
                      _items([n for n in gold.nodes if n.type not in events]))  # fmt: skip
    pe, ge = [n for n in pred.nodes if n.type in events], [n for n in gold.nodes if n.type in events]
    pairs = assign([[1.0 + similarity(p.name, g.name) if p.type == g.type else 0.0 for g in ge] for p in pe])
    return mapping | {pe[r].id: ge[c].id for r, c in pairs.items()}


def score(
    pred: ProcessModel,
    gold: ProcessModel,
    threshold: float = 0.8,
    matcher: Matcher | None = None,
    mapping: dict[str, str] | None = None,
) -> dict[str, float]:
    matcher = matcher or lexical_matcher(threshold)
    mapping = mapping if mapping is not None else match_nodes(pred, gold, matcher)
    pred_by_id = {n.id: n for n in pred.nodes}
    gold_by_id = {n.id: n for n in gold.nodes}

    pred_tasks = [n for n in pred.nodes if n.type in TASK_TYPES]
    gold_tasks = [n for n in gold.nodes if n.type in TASK_TYPES]
    matched_tasks = [(p, gold_by_id[mapping[p.id]]) for p in pred_tasks if p.id in mapping]

    lanes = matcher(
        [(lane.id, "lane", lane.name) for lane in pred.lanes], [(lane.id, "lane", lane.name) for lane in gold.lanes]
    )
    lane_hits = sum(lanes.get(p.lane_id or "") == g.lane_id for p, g in matched_tasks if g.lane_id)

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
