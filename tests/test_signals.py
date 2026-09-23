import unittest
from python.signals import fisher_two_sided, benjamini_hochberg, calculate_signals


class SignalTests(unittest.TestCase):
    def test_fisher_known_table_and_symmetry(self):
        self.assertAlmostEqual(fisher_two_sided(1,9,11,3),0.0027594561852200836,places=12)
        self.assertAlmostEqual(fisher_two_sided(11,3,1,9),fisher_two_sided(1,9,11,3),places=12)
        self.assertAlmostEqual(fisher_two_sided(5,5,5,5),1.0)

    def test_bh_known_example(self):
        actual=benjamini_hochberg([.01,.04,.03,.002])
        for a,b in zip(actual,[.02,.04,.04,.008]):self.assertAlmostEqual(a,b)

    def test_or_ci_and_full_family(self):
        rows=[]
        for cid,role,count in [(0,'transit',1),(0,'peripheral',9),(1,'transit',11),(1,'peripheral',3)]:
            rows.extend([dict(cluster_id=cid,role=role)]*count)
        result=calculate_signals(rows)
        self.assertEqual(result['n_tests'],12)
        row=next(r for r in result['tests'] if r['cluster_id']==0 and r['role']=='transit')
        self.assertAlmostEqual(row['odds_ratio'],1*3/(9*11))
        self.assertLess(row['ci_low'],row['odds_ratio']);self.assertGreater(row['ci_high'],row['odds_ratio'])
        self.assertGreaterEqual(row['q_value'],row['p_value'])
        self.assertEqual(row['signal'],'depleted')

    def test_zero_cells_and_unestimable(self):
        result=calculate_signals([{'cluster_id':0,'role':'transit'}]*4+[{'cluster_id':1,'role':'peripheral'}]*8)
        row=result['tests'][3]
        self.assertTrue(row['zero_correction']);self.assertAlmostEqual(row['odds_ratio'],4.5*8.5/(.5*.5))
        result=calculate_signals([{'cluster_id':0,'role':'transit'}]*3)
        self.assertTrue(all(r['odds_ratio'] is None and r['q_value']==1 for r in result['tests']))


if __name__=='__main__':unittest.main()
