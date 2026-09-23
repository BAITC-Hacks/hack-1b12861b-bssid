import unittest
from python.node_details import calculate_details, matched_amount
import networkx as nx
import pandas as pd


class NodeDetailsTests(unittest.TestCase):
    def test_no_reuse_same_day_or_expired_money(self):
        rows = [{'date': '2026-07-01', 'in_kzt': 100., 'out_kzt': 100.},
                {'date': '2026-07-02', 'in_kzt': 0., 'out_kzt': 60.},
                {'date': '2026-07-03', 'in_kzt': 50., 'out_kzt': 80.},
                {'date': '2026-07-06', 'in_kzt': 0., 'out_kzt': 100.}]
        self.assertEqual(matched_amount(rows), 100.)

    def test_directed_unique_ancestors_cycles_and_isolated_seed(self):
        graph = nx.DiGraph()
        graph.add_nodes_from(range(1, 8), is_seed=False)
        for gid in [1, 2, 7]:
            graph.nodes[gid]['is_seed'] = True
        graph.add_edges_from([(1, 3), (2, 3), (3, 4), (4, 3), (4, 5), (5, 6), (6, 1)])
        tx = pd.DataFrame([(1, 3, '2026-07-01', 20.), (1, 3, '2026-07-01', 30.),
                           (2, 3, '2026-07-01', 40.), (3, 4, '2026-07-02', 60.)],
                          columns=['src', 'dst', 'date', 'sum_kzt'])
        result = calculate_details(graph, tx)
        self.assertEqual(result['3']['seed_ancestors_4'], 2)
        self.assertEqual(result['1']['seed_ancestors_4'], 0)  # other seed is 5 hops away
        self.assertEqual(result['3']['cycle_size'], 5)
        self.assertEqual(result['3']['max_daily_payers'], 2)  # distinct payers, not transactions
        self.assertEqual(result['3']['matched_1_2_days_kzt'], 60.)
        self.assertEqual(result['7']['activity'], [])
        self.assertEqual(result['7']['seed_ancestors_4'], 0)
        self.assertEqual(result['7']['cycle_size'], 0)

    def test_self_loop(self):
        graph = nx.DiGraph()
        graph.add_node(1, is_seed=True)
        graph.add_edge(1, 1)
        tx = pd.DataFrame([(1, 1, '2026-07-01', 10.)], columns=['src','dst','date','sum_kzt'])
        row = calculate_details(graph, tx)['1']
        self.assertEqual(row['cycle_size'], 1)
        self.assertEqual(row['seed_ancestors_4'], 0)
        self.assertEqual(row['matched_1_2_days_kzt'], 0)


if __name__ == '__main__':
    unittest.main()
