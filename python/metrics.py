"""Explainable node metrics on the observed directed transfer graph."""
import json
import math

from . import etl  # Initializes optional project-local dependencies.
import networkx as nx
import pandas as pd


def calculate_metrics(graph):
    """One row per node; undefined out/in ratios remain NaN, never infinity."""
    if not graph.is_directed() or graph.is_multigraph():
        raise ValueError("Metrics require an aggregated directed DiGraph")
    in_deg = dict(graph.in_degree())
    out_deg = dict(graph.out_degree())
    in_kzt = dict(graph.in_degree(weight="sum_kzt"))
    out_kzt = dict(graph.out_degree(weight="sum_kzt"))
    rows = []
    for gid, attrs in sorted(graph.nodes(data=True)):
        incoming, outgoing = float(in_kzt[gid]), float(out_kzt[gid])
        rows.append({"gid": gid, "in_deg": in_deg[gid], "out_deg": out_deg[gid],
                     "in_kzt": incoming, "out_kzt": outgoing,
                     "pass_through": outgoing / incoming if incoming > 0 else float("nan"),
                     "depth": attrs["depth"], "is_seed": attrs["is_seed"],
                     "truncated_by_depth": attrs["depth"] == 4 and out_deg[gid] == 0})
    return pd.DataFrame(rows, columns=["gid", "in_deg", "out_deg", "in_kzt", "out_kzt",
                                       "pass_through", "depth", "is_seed", "truncated_by_depth"])


def export_metrics(graph, metrics, out_dir, node_details=None):
    """Persist metrics and enrich the same JSON contract produced by stage 1."""
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(out_dir / "nodes_metrics.csv", index=False)
    metrics.to_parquet(out_dir / "nodes_metrics.parquet", index=False)
    for row in metrics.itertuples(index=False):
        attrs = row._asdict()
        gid = attrs.pop("gid")
        attrs["pass_through"] = None if math.isnan(row.pass_through) else row.pass_through
        graph.nodes[gid].update(attrs)
    payload = {"directed": True,
               "nodes": [{"gid": str(gid), **attrs, **(node_details or {}).get(str(gid), {})} for gid, attrs in sorted(graph.nodes(data=True))],
               "edges": [{"from_gid": str(u), "to_gid": str(v), **attrs}
                         for u, v, attrs in graph.edges(data=True)]}
    (out_dir / "graph.json").write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    # GraphML cannot encode null: omit undefined ratio attributes there.
    graphml = graph.copy()
    for _, attrs in graphml.nodes(data=True):
        if attrs["pass_through"] is None:
            del attrs["pass_through"]
    nx.write_graphml(graphml, out_dir / "graph.graphml")


def validate_metrics(graph, metrics):
    """Independent aggregate invariants for the computed per-node values."""
    etl.require(len(metrics) == len(graph) and metrics.gid.is_unique, "metrics: node coverage mismatch")
    etl.require(set(metrics.gid) == set(graph), "metrics: gid mismatch")
    etl.require(int(metrics.in_deg.sum()) == graph.number_of_edges(), "metrics: incoming degree mismatch")
    etl.require(int(metrics.out_deg.sum()) == graph.number_of_edges(), "metrics: outgoing degree mismatch")
    turnover = math.fsum(attrs["sum_kzt"] for _, _, attrs in graph.edges(data=True))
    for column in ["in_kzt", "out_kzt"]:
        etl.require(math.isclose(math.fsum(metrics[column]), turnover, rel_tol=0, abs_tol=0.01),
                    f"metrics: {column} total mismatch")
    etl.require(metrics.pass_through.isna().eq(metrics.in_kzt.eq(0)).all(), "metrics: undefined ratio mismatch")
    return {"nodes": len(metrics), "undefined_pass_through": int(metrics.pass_through.isna().sum()),
            "pass_through_above_one": int(metrics.pass_through.gt(1).sum()),
            "isolated_nodes": int((metrics.in_deg.eq(0) & metrics.out_deg.eq(0)).sum()),
            "sum_in_kzt": math.fsum(metrics.in_kzt), "sum_out_kzt": math.fsum(metrics.out_kzt)}
