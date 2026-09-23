"""Observed daily flows and structural context; no inference of fund identity."""
from collections import defaultdict, deque
from . import etl
import networkx as nx
import pandas as pd


def matched_amount(activity):
    """FIFO capacity matching: each incoming/outgoing amount used at most once.

    Only transfers 1 or 2 calendar days after an incoming transfer qualify.
    Same-day transfers are excluded because within-day order is unknown.
    """
    pending, matched = deque(), 0.0
    for row in activity:
        day = pd.Timestamp(row['date']).toordinal()
        while pending and pending[0][0] < day - 2:
            pending.popleft()
        outgoing = row['out_kzt']
        while pending and outgoing > 0:
            amount = min(pending[0][1], outgoing)
            matched += amount
            outgoing -= amount
            pending[0][1] -= amount
            if pending[0][1] <= 0:
                pending.popleft()
        if row['in_kzt'] > 0:
            pending.append([day, row['in_kzt']])
    return matched


def calculate_details(graph, transactions):
    """Return JSON-safe details for every gid, including isolated seed nodes."""
    daily = defaultdict(lambda: defaultdict(lambda: {'in_kzt': 0.0, 'out_kzt': 0.0, 'payers': set()}))
    for row in transactions.itertuples(index=False):
        date = pd.Timestamp(row.date).date().isoformat()
        daily[int(row.src)][date]['out_kzt'] += float(row.sum_kzt)
        target = daily[int(row.dst)][date]
        target['in_kzt'] += float(row.sum_kzt)
        target['payers'].add(int(row.src))
    ancestors = defaultdict(int)
    for seed, attrs in graph.nodes(data=True):
        if attrs['is_seed']:
            for gid in nx.single_source_shortest_path_length(graph, seed, cutoff=4):
                if gid != seed:
                    ancestors[gid] += 1
    cycles = {}
    for members in nx.strongly_connected_components(graph):
        if len(members) > 1 or any(graph.has_edge(gid, gid) for gid in members):
            cycles.update({gid: len(members) for gid in members})
    result = {}
    for gid in graph:
        activity = [{'date': date, 'in_kzt': values['in_kzt'], 'out_kzt': values['out_kzt']}
                    for date, values in sorted(daily[gid].items())]
        result[str(gid)] = {
            'seed_ancestors_4': ancestors[gid],
            'cycle_size': cycles.get(gid, 0),
            'max_daily_payers': max((len(v['payers']) for v in daily[gid].values()), default=0),
            'matched_1_2_days_kzt': matched_amount(activity),
            'activity': activity,
        }
    return result
