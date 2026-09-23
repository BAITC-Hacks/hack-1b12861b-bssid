"""Verify actual serialized deliverables, not just their in-memory tables."""
import json
from . import etl
from .roles import ROLE_COLUMNS
import pandas as pd


def validate(out_dir, expected_nodes):
    roles = pd.read_csv(out_dir / 'nodes_roles.csv', dtype={'gid': 'int64'})
    clusters = pd.read_csv(out_dir / 'clusters.csv')
    top = pd.read_csv(out_dir / 'top_nodes.csv', dtype={'gid': 'int64'})
    etl.require(list(roles) == ROLE_COLUMNS, 'nodes_roles.csv schema mismatch')
    etl.require(list(clusters) == ['cluster_id', 'n_nodes', 'n_seed', 'sum_kzt_internal', 'top_gids', 'hypothesis'], 'clusters.csv schema mismatch')
    etl.require(list(top) == ['rank', 'gid', 'role', 'priority_score', 'why'], 'top_nodes.csv schema mismatch')
    etl.require(len(roles) == expected_nodes and roles.gid.is_unique, 'Role row count mismatch')
    etl.require(roles.notna().all().all() and clusters.notna().all().all() and top.notna().all().all(), 'Missing export fields')
    etl.require(roles.evidence.str.len().between(1, 200).all(), 'Invalid serialized evidence')
    etl.require(roles.role_score.between(0, 1).all() and roles.priority_score.between(0, 1).all(), 'Serialized score out of bounds')
    etl.require(len(top) >= min(20, expected_nodes) and top.gid.is_unique and top.priority_score.is_monotonic_decreasing, 'Invalid top ordering')
    etl.require(top['rank'].tolist() == list(range(1, len(top) + 1)), 'Invalid top ranks')
    etl.require(set(top.gid) <= set(roles.gid) and set(roles.cluster_id) == set(clusters.cluster_id), 'Broken export references')
    etl.require(roles.groupby('cluster_id').size().to_dict() == clusters.set_index('cluster_id').n_nodes.to_dict(), 'Cluster counts disagree')
    def reject(value):
        raise ValueError(f'Invalid JSON constant {value}')
    graph = json.loads((out_dir / 'graph.json').read_text(encoding='utf-8'), parse_constant=reject)
    gids = {node['gid'] for node in graph['nodes']}
    etl.require(len(graph['nodes']) == len(gids) == expected_nodes, 'Graph JSON node count mismatch')
    etl.require(gids == set(roles.gid.astype(str)), 'Graph JSON gid precision mismatch')
    etl.require(all(e['from_gid'] in gids and e['to_gid'] in gids for e in graph['edges']), 'Invalid JSON endpoints')
    records = roles.set_index('gid')
    for node in graph['nodes']:
        record = records.loc[int(node['gid'])]
        etl.require(node['role'] == record.role and node['cluster_id'] == record.cluster_id and node['evidence'] == record.evidence, 'JSON/CSV role mismatch')
    return {'status': 'passed', 'nodes_roles_rows': len(roles), 'clusters_rows': len(clusters), 'top_nodes_rows': len(top)}
