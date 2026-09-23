"""Parquet upload worker: stdin -> BytesIO -> analysis -> stdout. No output files."""
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
import time
import os

from . import etl, clustering, roles
from .metrics import calculate_metrics, validate_metrics
from .signals import calculate_signals
from .node_details import calculate_details
import pandas as pd
import pyarrow.parquet as pq
import pyarrow as pa

SCHEMAS = {'nodes.parquet': ['gid','depth','is_seed'],
           'edges.parquet': ['src','dst','sum_kzt','n_tx','depth'],
           'transactions.parquet': ['src','dst','date','sum_kzt']}
ROW_LIMITS = {'nodes.parquet':10000, 'edges.parquet':50000, 'transactions.parquet':200000}


def analyze_files(files):
    started = time.perf_counter()
    names = [f.get('name') for f in files]
    etl.require(len(names)==3 and set(names)==set(SCHEMAS), 'Expected exactly nodes.parquet, edges.parquet, transactions.parquet')
    frames = {}
    for file in files:
        name = file['name']
        raw = base64.b64decode(file['data'], validate=True)
        etl.require(0 < len(raw) <= 8*1024*1024, f'{name}: file limit is 8 MiB')
        parquet = pq.ParquetFile(BytesIO(raw))
        missing = set(SCHEMAS[name])-set(parquet.schema_arrow.names)
        etl.require(not missing, f'{name}: missing columns: {sorted(missing)}')
        etl.require(parquet.metadata.num_rows <= ROW_LIMITS[name], f'{name}: row limit is {ROW_LIMITS[name]}')
        etl.require(parquet.metadata.serialized_size <= 2*1024*1024, f'{name}: oversized metadata')
        etl.require(sum(parquet.metadata.row_group(i).total_byte_size for i in range(parquet.metadata.num_row_groups)) <= 128*1024*1024,
                    f'{name}: uncompressed size exceeds 128 MiB')
        for column in SCHEMAS[name]:
            dtype = parquet.schema_arrow.field(column).type
            valid = (pa.types.is_boolean(dtype) if column=='is_seed' else
                     (pa.types.is_floating(dtype) or pa.types.is_integer(dtype)) if column=='sum_kzt' else
                     (pa.types.is_date(dtype) or pa.types.is_timestamp(dtype) or pa.types.is_string(dtype) or pa.types.is_large_string(dtype)) if column=='date' else
                     pa.types.is_integer(dtype))
            etl.require(valid, f'{name}.{column}: incompatible type {dtype}')
        # Avoid decoding unrelated user-supplied columns.
        frames[name] = parquet.read(columns=SCHEMAS[name]).to_pandas()
    nodes, edges, tx = (frames[n] for n in SCHEMAS)
    etl.require(len(nodes)>0, 'nodes.parquet: no nodes')
    tx = etl.validate_inputs(nodes, edges, tx)
    for frame, columns in [(nodes,['gid']), (edges,['src','dst']), (tx,['src','dst'])]:
        etl.require(all(frame[c].between(0, 2**63-1).all() for c in columns), 'Identifiers must fit positive int64')
    flat = etl.aggregate(tx); etl.reconcile(flat, edges)
    graph = etl.build_graph(nodes, flat)
    depths = etl.shortest_depths(graph, nodes.loc[nodes.is_seed,'gid'].tolist())
    etl.require(all(depths.get(r.gid)==r.depth for r in nodes.itertuples()), 'Declared depth does not match directed seed reachability')
    etl.require(edges.depth.eq(edges.src.map(nodes.set_index('gid').depth)+1).all(), 'Edge discovery depth mismatch')
    metrics = calculate_metrics(graph)
    metrics_report = validate_metrics(graph, metrics)
    config_dir = Path(__file__).parent / 'config'
    cluster_config = json.loads((config_dir/'clustering.json').read_text())
    role_config = json.loads((config_dir/'roles.json').read_text())
    partition, stability, diagnostics = clustering.detect_communities(graph, cluster_config)
    clusters = clustering.summarize_clusters(graph, partition, stability, cluster_config)
    metrics['cluster_id'] = metrics.gid.map(partition).astype('int64')
    classified, resolved = roles.classify(metrics, role_config)
    ranked, top = roles.rank_nodes(classified, role_config)
    records = ranked.astype(object).where(pd.notna(ranked), None).to_dict('records')
    node_details = calculate_details(graph, tx)
    for record in records:
        record['gid'] = str(record['gid'])
        record.update(node_details[record['gid']])
    result_graph = {'directed':True, 'nodes':records,
                    'edges':[{'from_gid':str(u),'to_gid':str(v),**attrs} for u,v,attrs in graph.edges(data=True)]}
    csvs = {'nodes_roles.csv':ranked[roles.ROLE_COLUMNS].to_csv(index=False),
            'clusters.csv':clusters[['cluster_id','n_nodes','n_seed','sum_kzt_internal','top_gids','hypothesis']].to_csv(index=False),
            'top_nodes.csv':top.to_csv(index=False)}
    signal_report = calculate_signals(records)
    result_graph['report'] = {'status':'passed','stages':[1,2,3,4,5,6], 'source':'upload',
                              'metrics':metrics_report, 'elapsed_seconds':round(time.perf_counter()-started,4)}
    return {'graph':result_graph,'clusters':clusters.to_dict('records'), 'signals':signal_report,
            'rules':resolved,'csvs':csvs}


if __name__ == '__main__':
    try:
        def no_disk_writes(event, args):
            if event == 'open':
                _, mode, flags = args
                if (mode and any(c in mode for c in 'wax+')) or (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                    raise PermissionError('Upload worker prohibits disk writes')
            if event in ('tempfile.mkstemp','tempfile.mkdtemp'):
                raise PermissionError('Upload worker prohibits temporary files')
        sys.addaudithook(no_disk_writes)
        request = json.loads(sys.stdin.buffer.read(36*1024*1024))
        print(json.dumps(analyze_files(request['files']),ensure_ascii=False,allow_nan=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False))
        sys.exit(1)
