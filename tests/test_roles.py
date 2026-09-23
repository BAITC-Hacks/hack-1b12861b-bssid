import json
from pathlib import Path
import unittest
from python import etl, roles
import pandas as pd

CONFIG = json.loads((Path(__file__).parents[1] / 'python/config/roles.json').read_text())


class RoleTests(unittest.TestCase):
    def frame(self):
        rows = []
        for gid, indeg, outdeg, incoming, outgoing, depth, seed in [
            (1, 0, 0, 0, 0, 0, True), (2, 5, 0, 1e6, 0, 0, True),
            (3, 8, 0, 1e6, 0, 4, False), (4, 1, 1, 10000, 10000, 1, False),
            (5, 3, 1, 100000, 10000, 1, False), (6, 1, 10, 10000, 100000, 1, False),
            (7, 1, 0, 1e7, 0, 2, False), (8, 5, 8, 1e8, 1e8, 1, False),
            (9, 1, 1, 10000, 10000, 0, True)]:
            rows.append(dict(gid=gid, in_deg=indeg, out_deg=outdeg, in_kzt=incoming, out_kzt=outgoing,
                             pass_through=outgoing / incoming if incoming else float('nan'),
                             depth=depth, is_seed=seed, cluster_id=0, truncated_by_depth=depth == 4 and outdeg == 0))
        return pd.DataFrame(rows)

    def test_guardrails_and_rules(self):
        frame, _ = roles.classify(self.frame(), CONFIG)
        self.assertEqual(frame.role.tolist(), ['peripheral', 'peripheral', 'peripheral', 'transit',
                                              'consolidator', 'distributor', 'terminal', 'coordinator', 'peripheral'])
        self.assertTrue(frame.evidence.str.len().between(1, 200).all())
        self.assertTrue(frame.role_score.between(0, 1).all())

    def test_ranking_and_ties(self):
        frame, _ = roles.classify(self.frame(), CONFIG)
        ranked, top = roles.rank_nodes(frame, CONFIG)
        self.assertEqual(ranked.iloc[0].priority_score, 0)
        self.assertTrue(top.priority_score.is_monotonic_decreasing)
        self.assertTrue(ranked.priority_score.between(0, 1).all())
        self.assertTrue(top.why.str.contains('оборот').all())


if __name__ == '__main__':
    unittest.main()
