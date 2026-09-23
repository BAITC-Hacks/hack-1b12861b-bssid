import json
from pathlib import Path
import tempfile
import unittest

from python import etl
from python.metrics import calculate_metrics, export_metrics, validate_metrics
import networkx as nx


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.graph = nx.DiGraph()
        for gid, depth in [(100000000000000001, 0), (2, 1), (3, 2), (4, 0), (5, 4)]:
            self.graph.add_node(gid, depth=depth, is_seed=(depth == 0))
        self.graph.add_edge(100000000000000001, 2, sum_kzt=10000., n_transactions=2)
        self.graph.add_edge(2, 3, sum_kzt=25000., n_transactions=5)
        self.graph.add_edge(3, 2, sum_kzt=5000., n_transactions=1)
        self.graph.add_edge(3, 5, sum_kzt=5000., n_transactions=1)
        self.metrics = calculate_metrics(self.graph)

    def test_unique_neighbours_and_weighted_sums(self):
        row = self.metrics.set_index("gid").loc[2]
        self.assertEqual((row.in_deg, row.out_deg), (2, 1))
        self.assertEqual((row.in_kzt, row.out_kzt), (15000., 25000.))
        self.assertAlmostEqual(row.pass_through, 5 / 3)  # Must not clamp to one.
        self.assertEqual((row.depth, row.is_seed), (1, False))
        validate_metrics(self.graph, self.metrics)

    def test_zero_input_is_undefined_but_terminal_is_zero(self):
        rows = self.metrics.set_index("gid")
        self.assertTrue(rows.loc[[4, 100000000000000001], "pass_through"].isna().all())
        self.assertEqual(rows.loc[4, "in_deg"], 0)
        self.assertEqual(rows.loc[4, "out_kzt"], 0)
        self.assertEqual(rows.loc[5, "pass_through"], 0)
        self.assertEqual(rows.loc[5, "depth"], 4)

    def test_export_preserves_ids_null_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            export_metrics(self.graph, self.metrics, path)
            def reject_non_json(value):
                raise AssertionError(value)
            payload = json.loads((path / "graph.json").read_text(), parse_constant=reject_non_json)
            nodes = {node["gid"]: node for node in payload["nodes"]}
            self.assertIsNone(nodes["100000000000000001"]["pass_through"])
            self.assertEqual(nodes["2"]["in_deg"], 2)
            self.assertEqual(len(nx.read_graphml(path / "graph.graphml")), 5)
            restored = etl.pd.read_parquet(path / "nodes_metrics.parquet")
            etl.pd.testing.assert_frame_equal(self.metrics, restored)


if __name__ == "__main__":
    unittest.main()
