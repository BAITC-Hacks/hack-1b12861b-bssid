"""Ordered explicit rules. Scores measure rule support, not guilt/probability."""
import json
from . import etl
import pandas as pd

ROLE_COLUMNS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
ROLE_LABELS = {"coordinator": "связующего узла", "distributor": "распределения",
               "consolidator": "консолидации", "transit": "транзита", "terminal": "конечного получения"}


def classify(metrics, config):
    result = metrics.copy()
    turnover = result.in_kzt + result.out_kzt
    resolved = {**config,
                "coordinator_min_turnover": float(turnover.quantile(config["coordinator_turnover_quantile"])),
                "terminal_min_incoming": float(result.loc[result.in_kzt.gt(0), "in_kzt"].quantile(config["terminal_incoming_quantile"])) if result.in_kzt.gt(0).any() else 0.0}
    assigned = []
    for r in result.itertuples(index=False):
        role, score, rule = "peripheral", 0.25, "no_rule"
        warning = ""
        if r.truncated_by_depth:
            rule, score, warning = "depth_cutoff", 0.1, "Обрыв depth=4; продолжение неизвестно."
        elif r.is_seed and r.out_deg == 0:
            rule, score = "seed_no_outgoing", 0.1
            warning = "Seed без исходящих; нет наблюдаемых связей." if r.in_deg == 0 else "Seed только получатель; роль не установлена."
        elif (r.in_deg >= config["coordinator_in_degree"] and r.out_deg >= config["coordinator_out_degree"]
              and r.in_kzt + r.out_kzt >= resolved["coordinator_min_turnover"]):
            role, score, rule = "coordinator", 0.65, "coordinator_both_sides"
        elif r.out_deg >= config["distributor_out_degree"]:
            role, score, rule = "distributor", 0.75, "fan_out"
        elif (not r.is_seed and r.in_deg >= config["consolidator_in_degree"]
              and r.pass_through <= config["consolidator_max_pass_through"]):
            role, score, rule = "consolidator", 0.7, "many_in_low_out"
        elif (not r.is_seed and r.in_deg > 0 and r.out_deg > 0
              and config["transit_min_pass_through"] <= r.pass_through <= config["transit_max_pass_through"]):
            role, score, rule = "transit", 0.6, "balanced_observed_flow"
        elif (not r.is_seed and r.depth < 4 and r.out_deg == 0
              and r.in_kzt >= resolved["terminal_min_incoming"]):
            role, score, rule = "terminal", 0.5, "observed_terminal"
        if role != "peripheral":
            warning = f"Гипотеза {ROLE_LABELS[role]}."
        elif not warning:
            warning = "Порогов ролей не достиг; требуется контекст."
        if r.is_seed and r.out_deg > 0:
            score *= 0.8
            warning += " Вход seed неполон."
        ratio = "н/д" if pd.isna(r.pass_through) else f"{r.pass_through:.2f}"
        evidence = (f"{warning} Вход: {r.in_deg}/{r.in_kzt:.0f} KZT; "
                    f"выход: {r.out_deg}/{r.out_kzt:.0f} KZT; k={ratio}; depth={r.depth}.")
        etl.require(len(evidence) <= 200, "Evidence exceeds 200 characters")
        assigned.append((role, round(score, 4), rule, evidence))
    result[["role", "role_score", "rule_id", "evidence"]] = pd.DataFrame(assigned, index=result.index)
    descriptions = {
        "depth_cutoff": "depth=4 и out_deg=0: продолжение потока не наблюдается",
        "seed_no_outgoing": "is_seed=True и out_deg=0: недостаточно данных о функции seed",
        "coordinator_both_sides": f"in_deg≥{config['coordinator_in_degree']}, out_deg≥{config['coordinator_out_degree']}, оборот≥{resolved['coordinator_min_turnover']:.2f} KZT (Q{100 * config['coordinator_turnover_quantile']:g})",
        "fan_out": f"out_deg≥{config['distributor_out_degree']}; предыдущее правило не сработало",
        "many_in_low_out": f"не seed; in_deg≥{config['consolidator_in_degree']}; k≤{config['consolidator_max_pass_through']}; предыдущие правила не сработали",
        "balanced_observed_flow": f"не seed; in_deg>0, out_deg>0; {config['transit_min_pass_through']}≤k≤{config['transit_max_pass_through']}; предыдущие правила не сработали",
        "observed_terminal": f"не seed; depth<4; out_deg=0; in_kzt≥{resolved['terminal_min_incoming']:.2f} (Q{100 * config['terminal_incoming_quantile']:g} положительных входов); предыдущие правила не сработали",
        "no_rule": "Ни одно из упорядоченных правил ролей не выполнено; функция по этим метрикам не установлена"
    }
    result["rule_description"] = result.rule_id.map(descriptions)
    return result, resolved


def rank_nodes(frame, config):
    result = frame.copy()
    # Empirical CDF with ties equal; true zeros explicitly score zero.
    turnover = result.in_kzt + result.out_kzt
    degree = result.in_deg + result.out_deg
    result["priority_turnover"] = turnover.rank(method="max", pct=True).where(turnover.gt(0), 0)
    result["priority_degree"] = degree.rank(method="max", pct=True).where(degree.gt(0), 0)
    result["priority_role"] = result.role.map(config["role_weights"]) * result.role_score
    weights = config["priority_weights"]
    etl.require(abs(sum(weights.values()) - 1) < 1e-9, "Priority weights must sum to one")
    result["priority_score"] = sum(result[f"priority_{key}"] * weight for key, weight in weights.items()).round(6)
    result.loc[degree.eq(0), "priority_score"] = 0.0
    result["why"] = [f"P={p:.3f}: оборот {t:.2f}×{weights['turnover']}, связи {d:.2f}×{weights['degree']}, роль {s:.2f}×{weights['role']}. {e}"
                     for p, t, d, s, e in zip(result.priority_score, result.priority_turnover,
                                             result.priority_degree, result.priority_role, result.evidence)]
    ordered = result.sort_values(["priority_score", "gid"], ascending=[False, True])
    top = ordered.head(max(20, config["top_n"]))[["gid", "role", "priority_score", "why"]].copy()
    top.insert(0, "rank", range(1, len(top) + 1))
    return result, top


def export_roles(frame, top, resolved, out_dir):
    etl.require(frame.role.isin(resolved["role_weights"]).all(), "Unknown role")
    etl.require(frame.gid.is_unique and frame[ROLE_COLUMNS].notna().all().all(), "Incomplete role export")
    etl.require(frame.evidence.str.len().between(1, 200).all(), "Invalid evidence")
    etl.require(frame.role_score.between(0, 1).all() and frame.priority_score.between(0, 1).all(), "Invalid scores")
    etl.require(not frame.loc[frame.truncated_by_depth, "role"].eq("terminal").any(), "Cutoff assigned terminal")
    etl.require(frame.loc[frame.is_seed & frame.out_deg.eq(0), "role"].eq("peripheral").all(), "Inactive seed misclassified")
    frame[ROLE_COLUMNS].to_csv(out_dir / "nodes_roles.csv", index=False)
    frame.to_parquet(out_dir / "nodes_analysis.parquet", index=False)
    top.to_csv(out_dir / "top_nodes.csv", index=False)
    (out_dir / "role_rules_resolved.json").write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8")
    # Exact mandatory cluster schema; detailed diagnostics remain available separately.
    clusters = pd.read_csv(out_dir / "clusters.csv", dtype={"top_gids": str})
    clusters.to_csv(out_dir / "clusters_detailed.csv", index=False)
    clusters[["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]].to_csv(out_dir / "clusters.csv", index=False)
    (out_dir / "clusters.json").write_text(clusters.to_json(orient="records", force_ascii=False), encoding="utf-8")
    examples = []
    for role in ["coordinator", "transit", "terminal"]:
        candidates = frame[frame.role.eq(role)].sort_values(["priority_score", "gid"], ascending=[False, True])
        if len(candidates):
            r = candidates.iloc[0]
            examples.append(f"- `{int(r.gid)}` — **{role}**: {r.evidence} Правило `{r.rule_id}`. {r.why}")
    (out_dir / "demo_nodes.md").write_text("# Узлы для демо (выбраны из текущего расчёта)\n\n" + "\n\n".join(examples), encoding="utf-8")
    return {"role_counts": {k: int(frame.role.eq(k).sum()) for k in resolved["role_weights"]},
            "top_nodes": len(top), "max_evidence_length": int(frame.evidence.str.len().max()),
            "truncated_nodes": int(frame.truncated_by_depth.sum()),
            "seed_without_outgoing": int((frame.is_seed & frame.out_deg.eq(0)).sum())}
