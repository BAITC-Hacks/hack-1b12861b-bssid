import json
from pathlib import Path
import tempfile
import unittest

from python import etl
from python import clustering
from python.metrics import calculate_metrics, export_metrics
import networkx as nx


CONFIG = {"resolution": 1.0, "random_states": [42, 43, 44],
          "sensitivity_resolutions": [0.5, 1.5], "stability_min_jaccard": 0.8,
          "top_n": 2, "multi_seed_reference": 8, "reference_tolerance": 3}


class ClusteringTests(unittest.TestCase):
    def graph(self):
        graph = nx.DiGraph()
        for gid in range(1, 8):
            graph.add_node(gid, is_seed=gid in (1, 2, 7), depth=0 if gid in (1, 2, 7) else 1)
        for source, target, amount in [(1, 2, 10), (2, 1, 20), (2, 3, 100), (3, 1, 100),
                                        (4, 5, 100), (5, 6, 100), (6, 4, 100), (3, 4, 1)]:
            graph.add_edge(source, target, sum_kzt=float(amount))
        return graph

    def test_projection_sums_reciprocal_flows_and_preserves_isolate(self):
        graph = self.graph()
        graph.add_edge(1, 1, sum_kzt=5.)
        projected = clustering.undirected_projection(graph)
        self.assertEqual(projected[1][2]["weight"], 30)
        self.assertEqual(projected[1][1]["weight"], 5)
        self.assertEqual(projected.degree(7), 0)
        self.assertEqual(projected.size(weight="weight"), graph.size(weight="sum_kzt"))

    def test_summary_direction_top_and_accounting(self):
        graph = self.graph()
        partition = {1: 0, 2: 0, 3: 0, 4: 1, 5: 1, 6: 1, 7: 2}
        frame = clustering.summarize_clusters(graph, partition, {0: 1., 1: 1., 2: 1.}, CONFIG).set_index("cluster_id")
        self.assertEqual(frame.loc[0, "sum_kzt_internal"], 230)
        self.assertEqual(frame.loc[0, "sum_kzt_outgoing"], 1)
        self.assertEqual(frame.loc[1, "sum_kzt_incoming"], 1)
        self.assertEqual(frame.loc[0, "n_seed"], 2)
        self.assertEqual(json.loads(frame.loc[0, "top_gids"]), ["3", "1"])
        self.assertIn("seed=2", frame.loc[0, "hypothesis"])
        self.assertIn("Изолированный", frame.loc[2, "hypothesis"])

    def test_repeatability_and_no_loss_of_isolated_seed(self):
        graph = self.graph()
        left, scores, diagnostics = clustering.detect_communities(graph, CONFIG)
        right, _, _ = clustering.detect_communities(graph, CONFIG)
        self.assertEqual(left, right)
        self.assertEqual(set(left), set(graph))
        self.assertEqual(clustering.groups(left)[left[7]], {7})
        self.assertEqual(scores[left[7]], 1)
        self.assertEqual(len(diagnostics["sensitivity_runs"]), 6)

    def test_stability_is_label_invariant_and_detects_changed_membership(self):
        a = {1: 0, 2: 0, 3: 1, 4: 1}
        b = {1: 9, 2: 9, 3: 8, 4: 8}
        self.assertEqual(clustering.adjusted_rand(a, b), 1)
        self.assertEqual(clustering.stability_scores(a, [b]), {0: 1., 1: 1.})
        c = {1: 0, 2: 1, 3: 0, 4: 1}
        self.assertAlmostEqual(clustering.adjusted_rand(a, c), -0.5)
        self.assertEqual(clustering.stability_scores(a, [c]), {0: 1 / 3, 1: 1 / 3})

    def test_edgeless_graph_and_export_contract(self):
        graph = nx.DiGraph()
        graph.add_node(100000000000000001, is_seed=True, depth=0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            partition, diagnostics = clustering.run(graph, path, CONFIG)
            self.assertIsNone(diagnostics["selected_run"]["modularity"])
            self.assertEqual(diagnostics["stable_multi_seed_clusters"], 0)
            metrics = calculate_metrics(graph)
            metrics["cluster_id"] = metrics.gid.map(partition)
            export_metrics(graph, metrics, path)
            payload = json.loads((path / "graph.json").read_text())
            self.assertEqual(payload["nodes"][0]["gid"], "100000000000000001")
            self.assertEqual(payload["nodes"][0]["cluster_id"], 1)
            frame = etl.pd.read_csv(path / "clusters.csv")
            self.assertTrue({"cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"} <= set(frame))


if __name__ == "__main__":
    unittest.main()

