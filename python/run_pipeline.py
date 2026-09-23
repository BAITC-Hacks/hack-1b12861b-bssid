"""Local batch: ETL, metrics, communities, explicit roles, ranking, exports."""
import argparse
import json
from pathlib import Path
import sys
import time

# Support both `python python/run_pipeline.py` and `python -m python.run_pipeline`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python import etl
from python.metrics import calculate_metrics, export_metrics, validate_metrics
from python import clustering
from python import roles
from python import verify_outputs
from python.signals import calculate_signals
from python.node_details import calculate_details
import pandas as pd


def run(data_dir, out_dir, expected, clustering_config=None, roles_config=None):
    started = time.perf_counter()
    report = {"status": "failed", "stages": [1, 2, 3, 4, 5, 6]}
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        graph, etl_report = etl.run(data_dir, out_dir, expected)
        report["etl_seconds"] = etl_report["elapsed_seconds"]
        metrics = calculate_metrics(graph)
        report["metrics"] = validate_metrics(graph, metrics)
        if clustering_config is None:
            clustering_config = json.loads((Path(__file__).parent / "config/clustering.json").read_text(encoding="utf-8"))
        partition, diagnostics = clustering.run(graph, out_dir, clustering_config)
        metrics["cluster_id"] = metrics.gid.map(partition).astype("int64")
        report["clustering"] = {**diagnostics["selected_run"],
                                "stable_multi_seed_clusters": diagnostics["stable_multi_seed_clusters"],
                                "pairwise_ari_min": diagnostics["pairwise_ari_min"],
                                "reference_deviation": diagnostics["reference_deviation"]}
        if roles_config is None:
            roles_config = json.loads((Path(__file__).parent / "config/roles.json").read_text(encoding="utf-8"))
        classified, resolved = roles.classify(metrics, roles_config)
        ranked, top = roles.rank_nodes(classified, roles_config)
        report["roles"] = roles.export_roles(ranked, top, resolved, out_dir)
        node_details = calculate_details(graph, pd.read_parquet(data_dir / 'transactions.parquet'))
        export_metrics(graph, ranked, out_dir, node_details)
        report["exports"] = verify_outputs.validate(out_dir, len(graph))
        signals = calculate_signals(ranked[['cluster_id', 'role']].to_dict('records'))
        (out_dir / 'signals.json').write_text(json.dumps(signals, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        report['signals'] = {'tests': signals['n_tests'], 'q_below_005': sum(r['q_value']<0.05 for r in signals['tests'])}
        etl.require(time.perf_counter() - started <= expected["max_seconds"], "pipeline exceeds runtime budget")
        report["status"] = "passed"
        return report
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        report["elapsed_seconds"] = round(time.perf_counter() - started, 4)
        (out_dir / "pipeline_validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=etl.PROJECT_ROOT / "data/raw")
    parser.add_argument("--out", type=Path, default=etl.PROJECT_ROOT / "data/output")
    parser.add_argument("--expected", type=Path, default=Path(__file__).parent / "config/expected.json")
    parser.add_argument("--clustering-config", type=Path, default=Path(__file__).parent / "config/clustering.json")
    parser.add_argument("--roles-config", type=Path, default=Path(__file__).parent / "config/roles.json")
    args = parser.parse_args()
    try:
        report = run(args.data, args.out, json.loads(args.expected.read_text(encoding="utf-8")),
                     json.loads(args.clustering_config.read_text(encoding="utf-8")),
                     json.loads(args.roles_config.read_text(encoding="utf-8")))
    except Exception as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
