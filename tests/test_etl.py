import unittest
from python import etl
import pandas as pd


class ETLTests(unittest.TestCase):
    def setUp(self):
        self.tx = pd.DataFrame({"src": [1, 1, 2], "dst": [2, 2, 1],
                                "sum_kzt": [5000., 5000., 7000.],
                                "date": pd.to_datetime(["2026-07-03", "2026-07-01", "2026-07-02"])})
        self.flat = etl.aggregate(self.tx)
        self.edges = pd.DataFrame({"src": [1, 2], "dst": [2, 1],
                                   "sum_kzt": [10000., 7000.], "n_tx": [2, 1]})

    def test_aggregation_dates_and_direction(self):
        self.assertEqual(len(self.flat), 2)
        row = self.flat.iloc[0]
        self.assertEqual(row.sum_kzt, 10000.)
        self.assertEqual(row.n_transactions, 2)
        self.assertEqual(row.first_date, pd.Timestamp("2026-07-01"))
        self.assertEqual(row.last_date, pd.Timestamp("2026-07-03"))
        etl.reconcile(self.flat, self.edges)

    def test_corrupt_reference_rejected(self):
        for column, value in [("sum_kzt", 10001.), ("n_tx", 3), ("dst", 9)]:
            with self.subTest(column=column):
                bad = self.edges.copy()
                bad.loc[0, column] = value
                with self.assertRaises(etl.IntegrityError):
                    etl.reconcile(self.flat, bad)

    def test_isolated_seed_and_directed_depth(self):
        nodes = pd.DataFrame({"gid": [1, 2, 3], "depth": [0, 1, 0], "is_seed": [True, False, True]})
        graph = etl.build_graph(nodes, self.flat)
        self.assertEqual(len(graph), 3)
        self.assertEqual(graph.degree(3), 0)
        self.assertEqual(etl.shortest_depths(graph, [1, 3]), {1: 0, 3: 0, 2: 1})

    def test_identical_rows_are_not_dropped(self):
        doubled = etl.aggregate(pd.concat([self.tx, self.tx], ignore_index=True))
        self.assertEqual(doubled.n_transactions.sum(), 6)
        self.assertEqual(doubled.sum_kzt.sum(), 34000.)


if __name__ == "__main__":
    unittest.main()
