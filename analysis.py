from __future__ import annotations

from io import BytesIO
from pathlib import Path
from math import exp, log, sqrt

import networkx as nx
import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

ROLES = ["consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"]


def load_data(data_source: Path | dict[str, bytes]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if isinstance(data_source, dict):
        edges = pd.read_parquet(BytesIO(data_source["edges.parquet"]))
        nodes = pd.read_parquet(BytesIO(data_source["nodes.parquet"]))
        tx = pd.read_parquet(BytesIO(data_source["transactions.parquet"]))
    else:
        data_source = Path(data_source)
        edges = pd.read_parquet(data_source / "edges.parquet")
        nodes = pd.read_parquet(data_source / "nodes.parquet")
        tx = pd.read_parquet(data_source / "transactions.parquet")
    tx["date"] = pd.to_datetime(tx["date"])
    required = {
        "edges": (edges, {"src", "dst", "sum_kzt", "n_tx", "depth"}),
        "nodes": (nodes, {"gid", "depth", "is_seed"}),
        "transactions": (tx, {"src", "dst", "date", "sum_kzt"}),
    }
    for name, (frame, columns) in required.items():
        missing = columns - set(frame.columns)
        if missing:
            raise ValueError(f"В {name} не хватает колонок: {', '.join(sorted(missing))}")
    if nodes.gid.duplicated().any():
        raise ValueError("В nodes.parquet повторяются gid")
    if edges.duplicated(["src", "dst"]).any():
        raise ValueError("В edges.parquet повторяются пары плательщик-получатель")
    node_ids = set(nodes.gid)
    if not (set(edges.src) | set(edges.dst)).issubset(node_ids):
        raise ValueError("В edges.parquet есть gid, которых нет в nodes.parquet")
    tx_agg = tx.groupby(["src", "dst"], as_index=False).agg(sum_tx=("sum_kzt", "sum"), n_tx=("sum_kzt", "size"))
    check = edges.merge(tx_agg, on=["src", "dst"], how="outer", indicator=True)
    if (check._merge != "both").any():
        raise ValueError("Список пар в edges.parquet не совпадает с transactions.parquet")
    if not np.allclose(check.sum_kzt, check.sum_tx, rtol=1e-6, atol=0.01) or not (check.n_tx_x == check.n_tx_y).all():
        raise ValueError("Суммы или количество переводов в edges.parquet не сходятся с transactions.parquet")
    return edges, nodes, tx


def _rank(values: pd.Series) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce").fillna(0)
    return values.rank(method="average", pct=True).fillna(0).clip(0, 1)


def _fmt_amount(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _bh_adjust(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    order = np.argsort(p_values)
    adjusted = np.empty(len(p_values), dtype=float)
    running = 1.0
    for rank_index in range(len(order) - 1, -1, -1):
        original_index = order[rank_index]
        rank = rank_index + 1
        running = min(running, p_values[original_index] * len(order) / rank)
        adjusted[original_index] = min(1.0, running)
    return adjusted.tolist()


def _cluster_role_tests(df: pd.DataFrame) -> dict[tuple[int, str], dict]:
    role_labels = {
        "consolidator": "консолидация", "transit": "транзит",
        "distributor": "распределение", "terminal": "конечный получатель",
        "coordinator": "связующий узел",
    }
    total = len(df)
    role_totals = df.role.value_counts().to_dict()
    tests = []
    for cluster_id, group in df.groupby("cluster_id", sort=True):
        n = len(group)
        if n < 15 or n == total:
            continue
        for role, label in role_labels.items():
            inside = int((group.role == role).sum())
            outside = int(role_totals.get(role, 0) - inside)
            table = [[inside, n - inside], [outside, total - n - outside]]
            p_value = float(fisher_exact(table, alternative="two-sided").pvalue)

            # Haldane-Anscombe correction keeps the effect estimate finite for empty cells.
            a, b, c, d = inside + 0.5, n - inside + 0.5, outside + 0.5, total - n - outside + 0.5
            odds_ratio = (a * d) / (b * c)
            se_log_or = sqrt(1 / a + 1 / b + 1 / c + 1 / d)
            ci_low = exp(log(odds_ratio) - 1.96 * se_log_or)
            ci_high = exp(log(odds_ratio) + 1.96 * se_log_or)
            tests.append({
                "cluster_id": int(cluster_id), "role": role, "role_label": label,
                "inside_n": inside, "cluster_n": n, "outside_n": outside,
                "outside_total": total - n, "cluster_role_share": inside / n,
                "outside_role_share": outside / (total - n), "odds_ratio": odds_ratio,
                "ci95_low": ci_low, "ci95_high": ci_high, "p_value": p_value,
            })
    q_values = _bh_adjust([item["p_value"] for item in tests])
    for item, q_value in zip(tests, q_values):
        item["q_value"] = q_value
    return {(item["cluster_id"], item["role"]): item for item in tests}


def analyse(data_source: Path | dict[str, bytes]) -> dict:
    edges, nodes, tx = load_data(data_source)
    g = nx.DiGraph()
    g.add_nodes_from(nodes.gid.astype(int).tolist())
    for row in edges.itertuples(index=False):
        g.add_edge(int(row.src), int(row.dst), sum_kzt=float(row.sum_kzt), n_tx=int(row.n_tx))

    df = nodes[["gid", "depth", "is_seed"]].copy()
    df["gid"] = df.gid.astype(int)
    for name, values in {
        "in_deg": dict(g.in_degree()), "out_deg": dict(g.out_degree()),
        "in_kzt": dict(g.in_degree(weight="sum_kzt")),
        "out_kzt": dict(g.out_degree(weight="sum_kzt")),
        "in_tx": dict(g.in_degree(weight="n_tx")),
        "out_tx": dict(g.out_degree(weight="n_tx")),
    }.items():
        df[name] = df.gid.map(values).fillna(0)
    df["in_deg"] = df.in_deg.astype(int)
    df["out_deg"] = df.out_deg.astype(int)
    df["in_tx"] = df.in_tx.astype(int)
    df["out_tx"] = df.out_tx.astype(int)
    df["pagerank"] = df.gid.map(nx.pagerank(g, weight="sum_kzt")).fillna(0)
    between = nx.betweenness_centrality(g, k=min(350, len(g)), seed=17, weight=None)
    df["betweenness"] = df.gid.map(between).fillna(0)
    df["pass_through"] = np.where(df.in_kzt > 0, df.out_kzt / df.in_kzt.replace(0, np.nan), np.nan)
    df["truncated_by_depth"] = (df.depth == 4) & (df.out_deg == 0)
    df["retained_share"] = np.where(
        (df.in_kzt > 0) & (~df.is_seed), (1 - df.out_kzt / df.in_kzt).clip(0, 1), np.nan
    )

    seeds = df.loc[df.is_seed, "gid"].tolist()
    distance = {}
    for seed in seeds:
        for gid, d in nx.single_source_shortest_path_length(g, int(seed), cutoff=4).items():
            distance[gid] = min(distance.get(gid, 99), d)
    df["seed_distance"] = df.gid.map(distance).fillna(5).astype(int)

    ug = nx.Graph()
    ug.add_nodes_from(g.nodes)
    for src, dst, data in g.edges(data=True):
        if ug.has_edge(src, dst):
            ug[src][dst]["sum_kzt"] += data["sum_kzt"]
        else:
            ug.add_edge(src, dst, sum_kzt=data["sum_kzt"])
    communities = nx.community.louvain_communities(ug, weight="sum_kzt", seed=17)
    communities = sorted(communities, key=lambda group: (-len(group), min(group)))
    cluster_map = {int(gid): idx for idx, group in enumerate(communities, 1) for gid in group}
    df["cluster_id"] = df.gid.map(cluster_map).astype(int)

    # Each role score combines visible graph signals; seed incoming volume is excluded.
    in_degree_rank, out_degree_rank = _rank(df.in_deg), _rank(df.out_deg)
    in_amount_rank, out_amount_rank = _rank(df.in_kzt), _rank(df.out_kzt)
    centrality_rank = _rank(df.betweenness)
    df["score_consolidator"] = (0.50 * in_degree_rank + 0.30 * in_amount_rank +
                                0.20 * df.retained_share.fillna(0))
    ratio = df.pass_through
    df["score_transit"] = (1 - ((ratio - 1).abs() / 0.75)).clip(0, 1) * 0.65 + \
                          0.20 * in_degree_rank + 0.15 * out_degree_rank
    df["score_distributor"] = 0.55 * out_degree_rank + 0.30 * out_amount_rank + 0.15 * centrality_rank
    df["score_terminal"] = 0.60 * df.retained_share.fillna(0) + 0.25 * in_amount_rank + \
                           0.15 * (df.out_deg == 0).astype(float)
    df["score_coordinator"] = 0.60 * centrality_rank + 0.20 * in_degree_rank + 0.20 * out_degree_rank

    eligible = pd.DataFrame(index=df.index)
    eligible["consolidator"] = (df.in_deg >= 3) & (df.retained_share.fillna(0) >= 0.15) & (~df.is_seed)
    eligible["transit"] = (df.in_deg > 0) & (df.out_deg > 0) & ratio.between(0.65, 1.35)
    eligible["distributor"] = (df.out_deg >= 8) & (df.out_kzt > 0)
    eligible["terminal"] = (df.out_deg == 0) & (df.in_deg > 0) & (df.depth < 4)
    eligible["coordinator"] = (df.betweenness > 0) & (df.betweenness >= df.betweenness.quantile(0.985)) & \
                              ((df.in_deg + df.out_deg) >= 4)
    score_columns = {role: f"score_{role}" for role in ROLES[:-1]}
    candidates = pd.DataFrame({role: df[col].where(eligible[role], -1) for role, col in score_columns.items()})
    df["role"] = candidates.idxmax(axis=1)
    best_score = candidates.max(axis=1)
    df.loc[best_score < 0, "role"] = "peripheral"
    df["role_score"] = best_score.clip(0, 1)
    df.loc[df.role == "peripheral", "role_score"] = 0.35

    # Priority is a review queue aid, not a probability or a finding of wrongdoing.
    flow_signal = _rank(np.log1p(df.in_kzt + df.out_kzt))
    counterparty_signal = _rank(np.log1p(df.in_deg + df.out_deg))
    proximity_signal = (1 / (df.seed_distance + 1)).clip(0, 1)
    df["priority_role_component"] = 0.30 * df.role_score
    df["priority_flow_component"] = 0.25 * flow_signal
    df["priority_centrality_component"] = 0.20 * centrality_rank
    df["priority_counterparty_component"] = 0.15 * counterparty_signal
    df["priority_proximity_component"] = 0.10 * proximity_signal
    priority_parts = ["priority_role_component", "priority_flow_component",
                      "priority_centrality_component", "priority_counterparty_component",
                      "priority_proximity_component"]
    df["priority_score"] = df[priority_parts].sum(axis=1).clip(0, 1)
    df["priority_rank"] = df.priority_score.rank(method="min", ascending=False).astype(int)

    def evidence(row: pd.Series) -> str:
        role = row.role
        if role == "consolidator":
            text = f"Получает от {row.in_deg} клиентов {_fmt_amount(row.in_kzt)} KZT; внутри графа удерживает около {row.retained_share:.0%}."
        elif role == "transit":
            text = f"Получил {_fmt_amount(row.in_kzt)} и отправил {_fmt_amount(row.out_kzt)} KZT; отношение потоков {row.pass_through:.2f}."
        elif role == "distributor":
            text = f"Отправляет {row.out_deg} получателям на {_fmt_amount(row.out_kzt)} KZT; {row.out_tx} переводов."
        elif role == "terminal":
            text = f"Получил от {row.in_deg} клиентов {_fmt_amount(row.in_kzt)} KZT; исходящих связей нет, глубина {row.depth}."
        elif role == "coordinator":
            text = f"Связывает много участников ({row.in_deg} входящих, {row.out_deg} исходящих связей); высокий показатель посредничества."
        else:
            text = f"Яркая структурная роль не выявлена; глубина {row.depth}, {row.in_deg} входящих и {row.out_deg} исходящих связей."
        if row.truncated_by_depth:
            text += " Нет исходящих в выгрузке: достигнута граница 4 колен, это не подтверждает конечную роль."
        elif row.is_seed and role in ("transit", "distributor"):
            text += " Входящий поток seed-клиента в этой выгрузке неполон."
        return text[:200]

    df["evidence"] = df.apply(evidence, axis=1)
    role_tests = _cluster_role_tests(df)
    cluster_rows = []
    for cid, group in df.groupby("cluster_id", sort=True):
        gids = set(group.gid)
        internal = edges[edges.src.isin(gids) & edges.dst.isin(gids)]
        n_group = len(group)
        candidates = [item for (cluster_id, _), item in role_tests.items() if cluster_id == int(cid)]
        significant = [item for item in candidates if item["q_value"] < 0.05 and
                       item["odds_ratio"] > 1 and item["inside_n"] >= 3]
        enriched = [item for item in candidates if item["odds_ratio"] > 1]
        significant.sort(key=lambda item: (item["q_value"], -item["odds_ratio"]))
        enriched.sort(key=lambda item: (-item["odds_ratio"], item["q_value"]))
        candidates.sort(key=lambda item: (item["q_value"], -item["odds_ratio"]))
        selected = significant[0] if significant else (enriched[0] if enriched else (candidates[0] if candidates else None))
        cluster_summary = (f"{n_group} участников, {int(group.is_seed.sum())} исходных клиентов; "
                           f"внутренний оборот {_fmt_amount(internal.sum_kzt.sum())} KZT.")
        if n_group < 15:
            hypothesis = cluster_summary + " Малая группа: статистическую гипотезу о роли не формируем."
        elif selected is None:
            hypothesis = cluster_summary + " Для функциональных ролей недостаточно наблюдений для сравнения."
        else:
            in_share = selected["inside_n"] / selected["cluster_n"]
            out_share = selected["outside_n"] / selected["outside_total"] if selected["outside_total"] else 0
            evidence_text = (
                f"{selected['role_label']}: {selected['inside_n']}/{selected['cluster_n']} ({in_share:.1%}) "
                f"против {selected['outside_n']}/{selected['outside_total']} ({out_share:.1%}) вне кластера; "
                f"OR {selected['odds_ratio']:.2f} (95% ДИ {selected['ci95_low']:.2f}–{selected['ci95_high']:.2f}), "
                f"p={selected['p_value']:.3g}, q={selected['q_value']:.3g} (Fisher, BH)."
            )
            if significant:
                hypothesis = cluster_summary + " Разведочный сигнал: " + evidence_text + " Проверить на первичных операциях."
            elif selected["q_value"] < 0.05 and selected["odds_ratio"] > 1:
                hypothesis = cluster_summary + " Наблюдается повышенная доля роли, но случаев меньше трёх: " + evidence_text + " Сигнал не интерпретируется."
            elif selected["q_value"] < 0.05 and selected["odds_ratio"] < 1:
                hypothesis = cluster_summary + " Роль встречается реже, чем вне кластера: " + evidence_text + " Это не указывает на функцию кластера."
            else:
                hypothesis = cluster_summary + " Максимальное наблюдаемое отличие: " + evidence_text + " После поправки BH статистическая значимость не достигнута."
        cluster_rows.append({"cluster_id": int(cid), "n_nodes": int(len(group)),
                             "n_seed": int(group.is_seed.sum()), "sum_kzt_internal": float(internal.sum_kzt.sum()),
                             "top_gids": ",".join(map(str, group.nlargest(5, "priority_score").gid)),
                             "signal_role": selected["role"] if selected else "",
                             "cluster_role_share": selected["inside_n"] / selected["cluster_n"] if selected else np.nan,
                             "outside_role_share": selected["outside_n"] / selected["outside_total"] if selected and selected["outside_total"] else np.nan,
                             "odds_ratio": selected["odds_ratio"] if selected else np.nan,
                             "ci95_low": selected["ci95_low"] if selected else np.nan,
                             "ci95_high": selected["ci95_high"] if selected else np.nan,
                             "p_value": selected["p_value"] if selected else np.nan,
                             "q_value": selected["q_value"] if selected else np.nan,
                             "hypothesis": hypothesis})
    clusters = pd.DataFrame(cluster_rows)
    top = df.nlargest(50, "priority_score").copy()
    top_nodes = pd.DataFrame({"rank": np.arange(1, len(top) + 1), "gid": top.gid,
                              "role": top.role, "priority_score": top.priority_score,
                              "why": top.evidence})
    role_output = df[["gid", "role", "role_score", "cluster_id", "priority_score", "priority_rank", "evidence",
                      "in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx", "pagerank",
                      "betweenness", "pass_through", "depth", "is_seed", "truncated_by_depth",
                      *priority_parts]].copy()
    role_stats = pd.DataFrame(list(role_tests.values()), columns=[
        "cluster_id", "role", "role_label", "inside_n", "cluster_n", "outside_n", "outside_total",
        "cluster_role_share", "outside_role_share", "odds_ratio", "ci95_low", "ci95_high", "p_value", "q_value",
    ])
    return {"nodes": df, "edges": edges, "transactions": tx, "graph": g,
            "nodes_roles": role_output, "clusters": clusters, "cluster_role_stats": role_stats,
            "top_nodes": top_nodes}


def write_outputs(result: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    result["nodes_roles"].to_csv(out_dir / "nodes_roles.csv", index=False, encoding="utf-8-sig")
    result["clusters"].to_csv(out_dir / "clusters.csv", index=False, encoding="utf-8-sig")
    result["top_nodes"].to_csv(out_dir / "top_nodes.csv", index=False, encoding="utf-8-sig")
