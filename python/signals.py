"""Exploratory role enrichment: raw 2x2 Fisher tests, global BH correction."""
from collections import Counter
import math

ROLES = ['coordinator', 'consolidator', 'distributor', 'transit', 'terminal', 'peripheral']


def fisher_two_sided(a, b, c, d):
    """Sum hypergeometric probabilities no greater than the observed table."""
    n, row, column = a + b + c + d, a + b, a + c
    def logchoose(total, k):
        return math.lgamma(total + 1) - math.lgamma(k + 1) - math.lgamma(total - k + 1)
    def logprob(x):
        return logchoose(column, x) + logchoose(n-column, row-x) - logchoose(n, row)
    observed = logprob(a)
    return min(1.0, math.fsum(math.exp(logprob(x)) for x in range(max(0, row-(n-column)), min(row,column)+1)
                              if logprob(x) <= observed + 1e-9))


def benjamini_hochberg(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    adjusted = [1.0] * len(values)
    previous = 1.0
    for rank in range(len(order), 0, -1):
        idx = order[rank-1]
        previous = min(previous, values[idx] * len(values) / rank)
        adjusted[idx] = previous
    return adjusted


def calculate_signals(records):
    total = len(records)
    global_roles = Counter(r['role'] for r in records)
    sizes = Counter(r['cluster_id'] for r in records)
    counts = Counter((r['cluster_id'], r['role']) for r in records)
    results = []
    for cluster_id, size in sorted(sizes.items()):
        for role in ROLES:
            a = counts[cluster_id,role]; b = size-a
            c = global_roles[role]-a; d = total-size-c
            estimable = size > 0 and total > size and 0 < a+c < total
            corrected = estimable and min(a,b,c,d) == 0
            odds, low, high = None, None, None
            if estimable:
                aa, bb, cc, dd = [x + (0.5 if corrected else 0) for x in (a,b,c,d)]
                log_odds = math.log(aa)+math.log(dd)-math.log(bb)-math.log(cc)
                margin = 1.959963984540054 * math.sqrt(1/aa + 1/bb + 1/cc + 1/dd)
                odds, low, high = math.exp(log_odds), math.exp(log_odds-margin), math.exp(log_odds+margin)
            results.append({'cluster_id': int(cluster_id), 'role': role, 'inside_role': a, 'inside_other': b,
                            'outside_role': c, 'outside_other': d,
                            'inside_share': a/size, 'outside_share': c/(total-size) if total>size else None,
                            'odds_ratio': odds, 'ci_low': low, 'ci_high': high, 'zero_correction': corrected,
                            'estimable': estimable, 'sparse': min(a,b,c,d)<5,
                            'p_value': fisher_two_sided(a,b,c,d) if estimable else 1.0})
    for row, q in zip(results, benjamini_hochberg([r['p_value'] for r in results])):
        row['q_value'] = q
        row['signal'] = ('not_estimable' if not row['estimable'] else
                         ('enriched' if row['odds_ratio']>1 else 'depleted') if q<0.05 else 'not_detected')
    return {'tests': results, 'n_tests': len(results), 'alpha': 0.05,
            'test': 'Fisher two-sided', 'correction': 'Benjamini-Hochberg over all cluster-role pairs',
            'interval': '95% log-Wald; Haldane-Anscombe +0.5 to all cells if any zero',
            'exploratory': True}
