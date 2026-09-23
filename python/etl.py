"""Stage 1: audited transaction aggregation and directed graph construction."""
import argparse
from collections import deque
import json
from pathlib import Path
import sys
import time

# Optional project-local dependencies for the bundled Windows Python runtime.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
local_deps = PROJECT_ROOT / ".deps"
if local_deps.is_dir():
    sys.path.insert(0, str(local_deps))

import networkx as nx
import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_integer_dtype, is_numeric_dtype


class IntegrityError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise IntegrityError(message)


def validate_inputs(nodes, edges, tx, expected=None):
    schemas = [(nodes, ["gid", "depth", "is_seed"], "nodes"),
               (edges, ["src", "dst", "sum_kzt", "n_tx", "depth"], "edges"),
               (tx, ["src", "dst", "sum_kzt", "date"], "transactions")]
    for frame, columns, name in schemas:
        require(set(columns) <= set(frame.columns), f"{name}: missing columns: {sorted(set(columns)-set(frame.columns))}")
        require(not frame[columns].isna().any().any(), f"{name}: null values")
        for column in set(columns) & {"gid", "src", "dst", "depth", "n_tx"}:
            require(is_integer_dtype(frame[column]), f"{name}.{column}: integer required")
    require(is_bool_dtype(nodes.is_seed), "nodes.is_seed: boolean required")
    require(not nodes.gid.duplicated().any(), "nodes: duplicate gid")
    require(not edges.duplicated(["src", "dst"]).any(), "edges: duplicate pair")
    require(nodes.depth.between(0, 4).all(), "nodes: depth must be 0..4")
    require((nodes.is_seed == nodes.depth.eq(0)).all(), "seed/depth mismatch")
    gids = set(nodes.gid)
    for frame, name in [(edges, "edges"), (tx, "transactions")]:
        require((set(frame.src) | set(frame.dst)) <= gids, f"{name}: unknown endpoint")
        require(is_numeric_dtype(frame.sum_kzt), f"{name}: nonnumeric amount")
        require(np.isfinite(frame.sum_kzt).all() and (frame.sum_kzt > 0).all(),
                f"{name}: invalid amount")
    require((edges.n_tx > 0).all(), "edges: nonpositive transaction count")
    require((edges.depth > 0).all(), "edges: invalid discovery depth")
    tx = tx.copy()
    tx["date"] = pd.to_datetime(tx.date, errors="raise")
    require(not tx.date.isna().any(), "transactions: invalid dates")
    if expected is not None:
        require((tx.sum_kzt >= expected["min_transaction_kzt"]).all(), "transaction below threshold")
        require(((tx.date >= pd.Timestamp(expected["period_start"])) &
                 (tx.date < pd.Timestamp(expected["period_end"]) + pd.Timedelta(days=1))).all(),
                "transaction outside expected period")
    return tx


def aggregate(tx):
    # Repeated rows are retained: there is no transaction ID to prove duplication.
    return (tx.groupby(["src", "dst"], as_index=False, sort=True)
            .agg(sum_kzt=("sum_kzt", "sum"), n_transactions=("sum_kzt", "size"),
                 first_date=("date", "min"), last_date=("date", "max"))
            .rename(columns={"src": "from_gid", "dst": "to_gid"}))


def reconcile(flat, edges):
    merged = flat.merge(edges, left_on=["from_gid", "to_gid"], right_on=["src", "dst"],
                        how="outer", indicator=True, suffixes=("_computed", "_source"),
                        validate="one_to_one")
    require(merged._merge.eq("both").all(), "edges/transactions: pair mismatch")
    require(np.isclose(merged.sum_kzt_computed, merged.sum_kzt_source,
                       rtol=0, atol=0.01).all(), "edges/transactions: amount mismatch (>0.01 KZT)")
    require(merged.n_transactions.eq(merged.n_tx).all(), "edges/transactions: count mismatch")


def build_graph(nodes, flat):
    graph = nx.DiGraph()
    for row in nodes.itertuples(index=False):
        graph.add_node(int(row.gid), depth=int(row.depth), is_seed=bool(row.is_seed))
    for row in flat.itertuples(index=False):
        graph.add_edge(int(row.from_gid), int(row.to_gid), sum_kzt=float(row.sum_kzt),
                       n_transactions=int(row.n_transactions),
                       first_date=row.first_date.isoformat(), last_date=row.last_date.isoformat())
    return graph


def shortest_depths(graph, seeds):
    depths = dict.fromkeys(seeds, 0)
    queue = deque(seeds)
    while queue:
        source = queue.popleft()
        for target in graph.successors(source):
            if target not in depths:
                depths[target] = depths[source] + 1
                queue.append(target)
    return depths


def run(data_dir, out_dir, expected):
    started = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"status": "failed", "expected": expected}
    try:
        nodes = pd.read_parquet(data_dir / "nodes.parquet")
        edges = pd.read_parquet(data_dir / "edges.parquet")
        tx = pd.read_parquet(data_dir / "transactions.parquet")
        tx = validate_inputs(nodes, edges, tx, expected)
        flat = aggregate(tx)
        reconcile(flat, edges)
        graph = build_graph(nodes, flat)
        counts = {str(int(k)): int(v) for k, v in nodes.depth.value_counts().sort_index().items()}
        observed = {"nodes": len(graph), "seeds": int(nodes.is_seed.sum()),
                    "depth_counts": counts, "edges": graph.number_of_edges(),
                    "transactions": len(tx), "sum_kzt": float(flat.sum_kzt.sum())}
        report["observed"] = observed
        for key in ["nodes", "seeds", "depth_counts", "edges", "transactions"]:
            require(observed[key] == expected[key], f"{key}: observed {observed[key]}, expected {expected[key]}")
        require(abs(observed["sum_kzt"] - expected["sum_kzt"]) <= 0.01, "total turnover mismatch")
        depths = shortest_depths(graph, nodes.loc[nodes.is_seed, "gid"].tolist())
        mismatches = [int(r.gid) for r in nodes.itertuples() if depths.get(r.gid) != r.depth]
        report["shortest_depth_mismatches"] = mismatches
        require(not mismatches, f"declared depth differs from directed shortest distance: {len(mismatches)} nodes")
        source_depth = edges.src.map(nodes.set_index("gid").depth)
        require(edges.depth.eq(source_depth + 1).all(), "edge discovery depth mismatch")
        report["isolated_gids"] = sorted(nx.isolates(graph))
        report["isolated_seeds"] = sum(graph.nodes[g]["is_seed"] for g in report["isolated_gids"])
        report["weak_components"] = nx.number_weakly_connected_components(graph)
        components = sorted(nx.weakly_connected_components(graph), key=len, reverse=True)
        report["nontrivial_components"] = sum(len(c) > 1 for c in components)
        report["largest_component_nodes"] = len(components[0]) if components else 0
        report["nodes_outside_largest_component"] = len(graph) - report["largest_component_nodes"]
        report["self_loops"] = nx.number_of_selfloops(graph)
        report["identical_transaction_rows_retained"] = int(tx.duplicated().sum())
        report["period_observed"] = [tx.date.min().isoformat(), tx.date.max().isoformat()]
        flat.to_parquet(out_dir / "edge_list.parquet", index=False)
        flat.to_csv(out_dir / "edge_list.csv", index=False)
        nodes.sort_values("gid").to_parquet(out_dir / "nodes.parquet", index=False)
        nx.write_graphml(graph, out_dir / "graph.graphml")
        # int64 gids exceed JavaScript's safe integer range: JSON IDs must be strings.
        payload = {"directed": True,
                   "nodes": [{"gid": str(gid), **attrs} for gid, attrs in sorted(graph.nodes(data=True))],
                   "edges": [{"from_gid": str(u), "to_gid": str(v), **attrs} for u, v, attrs in graph.edges(data=True)]}
        (out_dir / "graph.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        require(time.perf_counter() - started <= expected["max_seconds"], "runtime exceeds budget")
        report["status"] = "passed"
        return graph, report
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        report["elapsed_seconds"] = round(time.perf_counter() - started, 4)
        (out_dir / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / "data/raw")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data/output")
    parser.add_argument("--expected", type=Path, default=Path(__file__).parent / "config/expected.json")
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    try:
        _, report = run(args.data, args.out, expected)
    except Exception as exc:
        print(f"ETL failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
