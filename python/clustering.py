"""Weighted Louvain communities, repeatability diagnostics and flow hypotheses."""
from collections import Counter, defaultdict
from itertools import combinations
import json
import math

from . import etl
import community as community_louvain
import networkx as nx
import pandas as pd


def undirected_projection(graph):
    """Use sum of reciprocal flows, retaining isolated nodes and self-loops."""
    if not graph.is_directed() or graph.is_multigraph():
        raise ValueError("Expected an aggregated directed graph")
    projected = nx.Graph()
    projected.add_nodes_from(sorted(graph.nodes))
    for source, target, attrs in sorted(graph.edges(data=True)):
        weight = float(attrs["sum_kzt"])
        etl.require(math.isfinite(weight) and weight > 0, "Invalid clustering weight")
        previous = projected.get_edge_data(source, target, {}).get("weight", 0.0)
        projected.add_edge(source, target, weight=previous + weight)
    return projected


def groups(partition):
    result = defaultdict(set)
    for gid, label in partition.items():
        result[label].add(gid)
    return dict(result)


def canonicalize(partition):
    # Stable labels for a fixed membership, independent of Louvain's label order.
    ordered = sorted(groups(partition).values(), key=lambda members: (-len(members), min(members)))
    return {gid: label for label, members in enumerate(ordered, start=1) for gid in sorted(members)}


def adjusted_rand(left, right):
    """Label-invariant adjusted Rand index, without an extra ML dependency."""
    etl.require(set(left) == set(right), "Partitions cover different nodes")
    choose2 = lambda value: value * (value - 1) // 2
    pairs = choose2(len(left))
    if pairs == 0:
        return 1.0
    joint = Counter((left[g], right[g]) for g in left)
    a = sum(choose2(v) for v in Counter(left.values()).values())
    b = sum(choose2(v) for v in Counter(right.values()).values())
    observed = sum(choose2(v) for v in joint.values())
    expected = a * b / pairs
    denominator = (a + b) / 2 - expected
    return (observed - expected) / denominator if denominator else 1.0


def stability_scores(selected, alternatives):
    """Worst best-match Jaccard over the other random restarts, per cluster."""
    selected_groups = groups(selected)
    scores = {label: 1.0 for label in selected_groups}
    for other in alternatives:
        sizes = Counter(other.values())
        for label, members in selected_groups.items():
            overlap = Counter(other[gid] for gid in members)
            best = max(n / (len(members) + sizes[other_label] - n)
                       for other_label, n in overlap.items())
            scores[label] = min(scores[label], best)
    return scores


def detect_communities(graph, config):
    states = config["random_states"]
    resolution = config["resolution"]
    etl.require(len(set(states)) == len(states) and len(states) >= 2, "Use at least two distinct random states")
    etl.require(resolution > 0 and all(r > 0 for r in config["sensitivity_resolutions"]), "Resolution must be positive")
    etl.require(0 <= config["stability_min_jaccard"] <= 1, "Invalid stability threshold")
    etl.require(config["top_n"] >= 1, "top_n must be positive")
    projected = undirected_projection(graph)
    has_edges = projected.number_of_edges() > 0

    def trials(value):
        rows, partitions = [], []
        for state in states:
            partition = (community_louvain.best_partition(projected, weight="weight", resolution=value,
                                                         random_state=state) if has_edges
                         else {gid: i for i, gid in enumerate(projected)})
            partition = canonicalize(partition)
            communities = groups(partition)
            modularity = (nx.community.modularity(projected, communities.values(), weight="weight", resolution=value)
                          if has_edges else None)
            counts = Counter(partition[gid] for gid, attrs in graph.nodes(data=True) if attrs["is_seed"])
            rows.append({"resolution": value, "random_state": state, "n_clusters": len(communities),
                         "multi_seed_clusters": sum(n > 1 for n in counts.values()), "modularity": modularity})
            partitions.append(partition)
        return rows, partitions

    rows, partitions = trials(resolution)
    # Only compare modularity within the configured resolution, never optimize for count=8.
    best = max(range(len(rows)), key=lambda i: rows[i]["modularity"] if has_edges else 0)
    selected = partitions[best]
    scores = stability_scores(selected, [p for i, p in enumerate(partitions) if i != best])
    aris = [adjusted_rand(a, b) for a, b in combinations(partitions, 2)]
    diagnostics = {"algorithm": "python-louvain", "version": community_louvain.__version__,
                   "projection": "undirected, weight(u,v)=sum_kzt(u,v)+sum_kzt(v,u)",
                   "config": config, "selected_run": rows[best], "runs": rows,
                   "pairwise_ari_min": min(aris), "pairwise_ari_mean": sum(aris) / len(aris),
                   "sensitivity_runs": []}
    for value in sorted(set(config["sensitivity_resolutions"]) - {resolution}):
        sensitivity, _ = trials(value)
        diagnostics["sensitivity_runs"].extend(sensitivity)
    diagnostics["reference_deviation"] = abs(rows[best]["multi_seed_clusters"] - config["multi_seed_reference"]) > config["reference_tolerance"]
    return selected, scores, diagnostics


def hypothesis(row):
    """Descriptive hypotheses, not individual roles or allegations."""
    internal, incoming, outgoing = row["sum_kzt_internal"], row["sum_kzt_incoming"], row["sum_kzt_outgoing"]
    total = internal + incoming + outgoing
    if total == 0:
        kind = "Изолированный фрагмент: наблюдаемых переводов нет"
    elif row["internal_share"] >= 0.8:
        kind = "Гипотеза: преимущественно внутренний оборот"
    elif outgoing > 1.5 * incoming:
        kind = "Гипотеза: передача средств другим сообществам"
    elif incoming > 1.5 * outgoing:
        kind = "Гипотеза: получение средств из других сообществ"
    else:
        kind = "Гипотеза: смешанный обмен между сообществами"
    return (f"{kind}; узлов={row['n_nodes']}, seed={row['n_seed']}; "
            f"внутри={internal:.2f}, вход={incoming:.2f}, выход={outgoing:.2f} KZT; "
            f"4-е колено={row['n_depth4']}. Только наблюдаемые потоки; роль не установлена.")


def summarize_clusters(graph, partition, stability, config):
    etl.require(set(graph) == set(partition), "Cluster coverage mismatch")
    communities = groups(partition)
    internal, incoming, outgoing = Counter(), Counter(), Counter()
    for source, target, attrs in graph.edges(data=True):
        left, right, amount = partition[source], partition[target], attrs["sum_kzt"]
        if left == right:
            internal[left] += amount
        else:
            outgoing[left] += amount
            incoming[right] += amount
    turnover = dict(graph.degree(weight="sum_kzt"))
    rows = []
    for label, members in sorted(communities.items()):
        total = internal[label] + incoming[label] + outgoing[label]
        top = sorted(members, key=lambda gid: (-turnover[gid], gid))[:config["top_n"]]
        row = {"cluster_id": label, "n_nodes": len(members),
               "n_seed": sum(graph.nodes[gid]["is_seed"] for gid in members),
               "sum_kzt_internal": float(internal[label]),
               "top_gids": json.dumps([str(gid) for gid in top]),
               "sum_kzt_incoming": float(incoming[label]), "sum_kzt_outgoing": float(outgoing[label]),
               "internal_share": internal[label] / total if total else 0.0,
               "n_depth4": sum(graph.nodes[gid]["depth"] == 4 for gid in members),
               "stability_min_jaccard": stability[label],
               "is_stable": stability[label] >= config["stability_min_jaccard"]}
        row["hypothesis"] = hypothesis(row)
        rows.append(row)
    result = pd.DataFrame(rows, columns=["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal",
                                        "top_gids", "hypothesis", "sum_kzt_incoming", "sum_kzt_outgoing",
                                        "internal_share", "n_depth4", "stability_min_jaccard", "is_stable"])
    total = math.fsum(attrs["sum_kzt"] for _, _, attrs in graph.edges(data=True))
    etl.require(int(result.n_nodes.sum()) == len(graph), "Cluster node total mismatch")
    etl.require(int(result.n_seed.sum()) == sum(a["is_seed"] for _, a in graph.nodes(data=True)), "Cluster seed total mismatch")
    etl.require(math.isclose(math.fsum(result.sum_kzt_internal) + math.fsum(result.sum_kzt_outgoing), total,
                            rel_tol=0, abs_tol=0.01), "Cluster turnover mismatch")
    etl.require(math.isclose(math.fsum(result.sum_kzt_incoming), math.fsum(result.sum_kzt_outgoing),
                            rel_tol=0, abs_tol=0.01), "Cluster boundary flow mismatch")
    return result


def run(graph, out_dir, config):
    partition, stability, diagnostics = detect_communities(graph, config)
    clusters = summarize_clusters(graph, partition, stability, config)
    diagnostics["stable_multi_seed_clusters"] = int((clusters.n_seed.gt(1) & clusters.is_stable).sum())
    diagnostics["stable_clusters"] = int(clusters.is_stable.sum())
    diagnostics["singleton_clusters"] = int(clusters.n_nodes.eq(1).sum())
    out_dir.mkdir(parents=True, exist_ok=True)
    clusters.to_csv(out_dir / "clusters.csv", index=False)
    pd.DataFrame([{"gid": gid, "cluster_id": label} for gid, label in sorted(partition.items())]).to_parquet(
        out_dir / "nodes_clusters.parquet", index=False)
    (out_dir / "clustering_diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    nx.set_node_attributes(graph, partition, "cluster_id")
    return partition, diagnostics
